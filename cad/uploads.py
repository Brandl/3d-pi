"""Opaque project files: never parsed, executed, or adopted as CAD revisions."""

import hashlib
import re
import time
import unicodedata
import uuid

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import Field
from starlette.datastructures import UploadFile

from cad.projects import project_id
from cad.schema import Strict
from cad.storage import Missing, Conflict

MAX_FILE = 10 * 1024 * 1024
MAX_BODY = MAX_FILE + 64 * 1024
MAX_PROJECT = 512 * 1024 * 1024
MAX_FILES = 500
UPLOAD_ROUTE = re.compile(r"^/projects/[a-z0-9][a-z0-9-]{0,63}/api/uploads$")
DDL = """
CREATE TABLE IF NOT EXISTS project_uploads (
 id TEXT PRIMARY KEY, filename TEXT NOT NULL, size INTEGER NOT NULL,
 sha256 TEXT NOT NULL, note TEXT NOT NULL, created REAL NOT NULL,
 version INTEGER NOT NULL DEFAULT 1
);
"""


class NoteRequest(Strict):
    note: str = Field(max_length=4000)
    version: int = Field(ge=1)


def filename(value):
    value = unicodedata.normalize("NFC", value or "").strip()
    if (
        not value
        or len(value) > 240
        or value in (".", "..")
        or any(c in value for c in "/\\")
        or any(unicodedata.category(c).startswith("C") for c in value)
    ):
        raise HTTPException(422, "Invalid filename")
    return value


def selected(catalog):
    if not project_id.get():
        raise HTTPException(404, "Uploads require a project")
    return catalog.selected()


def get(store, ident):
    with store.connection() as db:
        row = db.execute("SELECT * FROM project_uploads WHERE id=?", (ident,)).fetchone()
    if not row:
        raise Missing("Unknown upload")
    return dict(row)


def install(app, catalog):
    @app.get("/api/uploads")
    def listing():
        store = selected(catalog)
        with store.connection() as db:
            rows = [
                dict(r)
                for r in db.execute("SELECT * FROM project_uploads ORDER BY created DESC,id")
            ]
        return {
            "uploads": rows,
            "max_file_bytes": MAX_FILE,
            "max_project_bytes": MAX_PROJECT,
            "max_files": MAX_FILES,
        }

    @app.post("/api/uploads", status_code=201)
    async def upload(request: Request):
        store = selected(catalog)
        async with request.form(max_files=1, max_fields=1, max_part_size=64 * 1024) as form:
            if set(form) - {"file", "note"} or len(form.multi_items()) != len(form):
                raise HTTPException(422, "Expected one file and optional note")
            item = form.get("file")
            note = form.get("note", "")
            if not isinstance(item, UploadFile) or not isinstance(note, str):
                raise HTTPException(422, "Expected one file and optional note")
            name = filename(item.filename)
            if len(note) > 4000:
                raise HTTPException(422, "Note exceeds 4000 characters")
            data = await item.read(MAX_FILE + 1)
            if len(data) > MAX_FILE:
                raise HTTPException(413, "File exceeds 10 MiB")
        ident = uuid.uuid4().hex
        directory = store.root / "uploads"
        directory.mkdir(mode=0o700, exist_ok=True)
        path = directory / ident
        created = False
        try:
            with store.connection() as db:
                db.execute("BEGIN IMMEDIATE")
                count, size = db.execute(
                    "SELECT count(*),coalesce(sum(size),0) FROM project_uploads"
                ).fetchone()
                if count >= MAX_FILES or size + len(data) > MAX_PROJECT:
                    raise HTTPException(413, "Project upload quota reached")
                with path.open("xb") as output:
                    created = True
                    output.write(data)
                db.execute(
                    "INSERT INTO project_uploads VALUES (?,?,?,?,?,?,1)",
                    (ident, name, len(data), hashlib.sha256(data).hexdigest(), note, time.time()),
                )
        except BaseException:
            if created:
                path.unlink(missing_ok=True)
            raise
        return get(store, ident)

    @app.patch("/api/uploads/{ident}")
    def edit_note(ident: str, request: NoteRequest):
        store = selected(catalog)
        with store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT version FROM project_uploads WHERE id=?", (ident,)).fetchone()
            if not row:
                raise Missing("Unknown upload")
            if row[0] != request.version:
                raise Conflict("Note changed elsewhere; refresh before editing")
            db.execute(
                "UPDATE project_uploads SET note=?,version=version+1 WHERE id=?",
                (request.note, ident),
            )
        return get(store, ident)

    @app.delete("/api/uploads/{ident}", status_code=204)
    def delete(ident: str):
        store = selected(catalog)
        row = get(store, ident)
        with store.connection() as db:
            db.execute("DELETE FROM project_uploads WHERE id=?", (row["id"],))
        (store.root / "uploads" / row["id"]).unlink(missing_ok=True)

    @app.api_route("/downloads/uploads/{ident}/file", methods=["GET", "HEAD"])
    def download(ident: str):
        store = selected(catalog)
        row = get(store, ident)
        path = store.root / "uploads" / row["id"]
        if not path.is_file() or path.is_symlink():
            raise Missing("Upload file unavailable")
        return FileResponse(
            path,
            filename=row["filename"],
            media_type="application/octet-stream",
            headers={
                "X-Content-Type-Options": "nosniff",
                "Content-Security-Policy": "sandbox",
                "Cache-Control": "no-store",
            },
        )
