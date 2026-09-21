"""Explicit design commits and related outputs; independent of legacy publication."""

import hashlib
import json
import re
import time
import unicodedata
import uuid

from pydantic import Field, field_validator
from cad.schema import Strict, Document
from cad.storage import Conflict, Missing


class CommitRequest(Strict):
    revision: str = Field(pattern=r"^[a-f0-9]{32}$")
    base_revision: str | None = Field(pattern=r"^[a-f0-9]{32}$")
    expected_generation: int = Field(ge=0)
    request_key: str = Field(min_length=8, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=80)
    icon: str = Field(min_length=1, max_length=16)
    source_commit: str = Field(pattern=r"^(?:[a-f0-9]{40}|[a-f0-9]{64})$")
    source_file: str = Field(min_length=1, max_length=240)
    source_document: Document

    @field_validator("name")
    @classmethod
    def clean_name(cls, value):
        if value != value.strip() or any(unicodedata.category(c).startswith("C") for c in value):
            raise ValueError("Use a short, single-line name without control characters")
        return value

    @field_validator("icon")
    @classmethod
    def emoji(cls, value):
        # Bounded Unicode symbol/emoji sequence (including modifiers, VS16 and ZWJ).
        # No ASCII labels, whitespace, bidi controls, markup or arbitrary text.
        if value.isascii() or not any(unicodedata.category(c).startswith("S") for c in value):
            raise ValueError("icon must contain a Unicode symbol or emoji")
        if any(
            not (unicodedata.category(c) in {"So", "Sm", "Sk", "Mn", "Me"} or c == "\u200d")
            for c in value
        ):
            raise ValueError("Use a Unicode symbol or emoji, not a text label")
        return value

    @field_validator("source_file")
    @classmethod
    def relative_file(cls, value):
        if (
            value.startswith("/")
            or "\\" in value
            or any(p in ("", ".", "..") for p in value.split("/"))
            or not re.fullmatch(r"[A-Za-z0-9_. /-]+", value)
        ):
            raise ValueError("source_file must be a relative repository path")
        return value


class AssetRequest(Strict):
    commit: str = Field(pattern=r"^[a-f0-9]{32}$")
    revision: str = Field(pattern=r"^[a-f0-9]{32}$")
    role: str = Field(pattern=r"^(inspection|print|test)$")
    name: str = Field(min_length=1, max_length=80)
    note: str = Field(max_length=16000, default="")
    request_key: str = Field(min_length=8, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")

    _name = field_validator("name")(CommitRequest.clean_name.__func__)


DDL = """
CREATE TABLE IF NOT EXISTS design_state (
 singleton INTEGER PRIMARY KEY CHECK(singleton=1), commit_id TEXT, generation INTEGER NOT NULL);
INSERT OR IGNORE INTO design_state VALUES (1,NULL,0);
CREATE TABLE IF NOT EXISTS design_commits (
 id TEXT PRIMARY KEY, generation INTEGER UNIQUE NOT NULL, revision TEXT NOT NULL,
 parent TEXT, name TEXT NOT NULL, icon TEXT NOT NULL, created REAL NOT NULL,
 source_commit TEXT NOT NULL, source_file TEXT NOT NULL, document_hash TEXT NOT NULL,
 request_key TEXT UNIQUE NOT NULL, request_hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS design_assets (
 id TEXT PRIMARY KEY, commit_id TEXT NOT NULL, revision TEXT NOT NULL,
 role TEXT NOT NULL, name TEXT NOT NULL, note TEXT NOT NULL, created REAL NOT NULL,
 request_key TEXT UNIQUE NOT NULL, request_hash TEXT NOT NULL);
"""


def snapshot(db):
    state = dict(db.execute("SELECT commit_id,generation FROM design_state").fetchone())
    state["commits"] = [
        dict(r)
        for r in db.execute(
            "SELECT id,generation,revision,parent,name,icon,created,source_commit,source_file,document_hash FROM design_commits ORDER BY generation"
        )
    ]
    state["assets"] = [
        dict(r)
        for r in db.execute(
            "SELECT id,commit_id,revision,role,name,note,created FROM design_assets ORDER BY created"
        )
    ]
    state["revision"] = state["commits"][-1]["revision"] if state["commits"] else None
    return state


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def ready(store, db, revision):
    row = store.decode(db.execute("SELECT * FROM revisions WHERE id=?", (revision,)).fetchone())
    if row["status"] != "ready" or not row["result"]["report"]["valid"]:
        raise Conflict("Only ready, valid geometry may be committed or attached")
    return row


def commit(store, request):
    payload = request.model_dump()
    request_hash = digest(payload)
    with store.connection() as db:
        db.execute("BEGIN IMMEDIATE")
        prior = db.execute(
            "SELECT * FROM design_commits WHERE request_key=?", (request.request_key,)
        ).fetchone()
        if prior:
            if prior["request_hash"] != request_hash:
                raise Conflict("Request key already used for different input")
            return dict(prior)
        current = snapshot(db)
        legacy = db.execute("SELECT revision FROM state").fetchone()["revision"]
        base = current["revision"] or legacy
        if request.expected_generation != current["generation"] or request.base_revision != base:
            raise Conflict("Working design changed; inspect before committing. No changes applied.")
        row = ready(store, db, request.revision)
        if db.execute(
            "SELECT 1 FROM design_assets WHERE revision=?", (request.revision,)
        ).fetchone():
            raise Conflict("This revision is a related output, not a design change")
        if request.source_document.model_dump(mode="json") != row["document"]:
            raise Conflict("Committed Git document does not match this CAD revision")
        if current["commits"] and current["commits"][-1]["document_hash"] == row["content_hash"]:
            raise Conflict("No design change; renders and exports do not create timeline entries")
        ident = uuid.uuid4().hex
        generation = current["generation"] + 1
        db.execute(
            "INSERT INTO design_commits VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                ident,
                generation,
                request.revision,
                current["commit_id"],
                request.name,
                request.icon,
                time.time(),
                request.source_commit,
                request.source_file,
                row["content_hash"],
                request.request_key,
                request_hash,
            ),
        )
        db.execute("UPDATE design_state SET commit_id=?,generation=?", (ident, generation))
        return dict(db.execute("SELECT * FROM design_commits WHERE id=?", (ident,)).fetchone())


def attach(store, request):
    request_hash = digest(request.model_dump())
    with store.connection() as db:
        db.execute("BEGIN IMMEDIATE")
        prior = db.execute(
            "SELECT * FROM design_assets WHERE request_key=?", (request.request_key,)
        ).fetchone()
        if prior:
            if prior["request_hash"] != request_hash:
                raise Conflict("Request key already used for different input")
            return dict(prior)
        if not db.execute("SELECT 1 FROM design_commits WHERE id=?", (request.commit,)).fetchone():
            raise Missing("Unknown design commit in this project")
        ready(store, db, request.revision)
        ident = uuid.uuid4().hex
        db.execute(
            "INSERT INTO design_assets VALUES (?,?,?,?,?,?,?,?,?)",
            (
                ident,
                request.commit,
                request.revision,
                request.role,
                request.name,
                request.note,
                time.time(),
                request.request_key,
                request_hash,
            ),
        )
        return dict(db.execute("SELECT * FROM design_assets WHERE id=?", (ident,)).fetchone())
