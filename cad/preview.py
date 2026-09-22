"""Read-only public demo gateway. Never tunnel the modeling service directly."""

import asyncio
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from cad.auth import PasswordGate, PasswordMiddleware
from cad.projects import ProjectScope, prefix, project_id

ORIGIN = os.environ.get("CAD_ORIGIN", "http://127.0.0.1:8765")
DIST = Path(__file__).resolve().parent.parent / "web" / "dist"
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.state.gate = PasswordGate.from_env()
app.add_middleware(PasswordMiddleware, owner=app)
app.add_middleware(ProjectScope)


def fetch(path):
    try:
        with urllib.request.urlopen(ORIGIN + prefix() + path, timeout=15) as response:
            return response.read(), response.headers.get("Content-Type", "application/octet-stream")
    except urllib.error.HTTPError as exc:
        raise HTTPException(
            exc.code if exc.code in (404, 409) else 502, "CAD project or resource unavailable"
        ) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise HTTPException(502, "Local CAD service unavailable") from exc


def upstream(path):
    return json.loads(fetch(path)[0])


def published(revision):
    if not re.fullmatch(r"[a-f0-9]{32}", revision):
        raise HTTPException(404)
    state = upstream("/api/state")
    workspace = state.get("workspace", {})
    registered = {r["revision"] for r in workspace.get("commits", []) + workspace.get("assets", [])}
    if project_id.get() and (
        revision in registered
        or any(r["id"] == revision and r["status"] == "ready" for r in state["history"])
    ):
        return upstream(f"/api/revisions/{revision}")
    if revision not in {p["revision"] for p in state["publications"]}:
        raise HTTPException(404, "Only published models are available in the preview")
    return upstream(f"/api/revisions/{revision}")


@app.get("/api/state")
def state():
    data = upstream("/api/state")
    # Authenticated project workspaces get build status, never raw source documents.
    return {
        "revision": data["revision"],
        "generation": data["generation"],
        "workspace": data.get("workspace") if project_id.get() else None,
        "candidate_names": {r["id"]: r.get("name", r["id"][:8]) for r in data["history"]}
        if project_id.get()
        else {},
        "candidates": data.get(
            "candidates",
            [
                r["id"]
                for r in data["history"]
                if r["status"] == "ready"
                and r["id"] not in {p["revision"] for p in data["publications"]}
            ],
        )
        if project_id.get()
        else [],
        "history": ([{'id': r['id'], 'status': r['status']} for r in data['history']] if project_id.get() else ([{"id": data["revision"], "status": "ready"}] if data["revision"] else [])),
        "publications": [
            {
                key: item.get(key)
                for key in ("generation", "revision", "operation", "created", "name")
            }
            for item in data["publications"]
        ],
    }


@app.get("/api/revisions/{revision}")
def inspect(revision: str):
    row = published(revision)
    return {
        "id": revision,
        "document": {"name": row["document"]["name"], "outputs": row["document"]["outputs"]},
        "result": {"report": row["result"]["report"], "exports": row["result"]["exports"]},
    }


@app.get("/api/revisions/{revision}/tree")
def assembly_tree(revision: str):
    from cad.introspection import tree

    return tree(published(revision))


@app.get("/api/revisions/{revision}/components/{component_id}")
def component_inspect(revision: str, component_id: str):
    from cad.introspection import component

    try:
        return component(published(revision), component_id)
    except KeyError:
        raise HTTPException(404, "Unknown component ID") from None


@app.api_route("/api/revisions/{revision}/artifacts/{filename}", methods=["GET", "HEAD"])
@app.api_route("/downloads/{revision}/{filename}", methods=["GET", "HEAD"])
def artifact(revision: str, filename: str, request: Request):
    row = published(revision)
    allowed = {
        "preview.json",
        "render-iso.png",
        "render-top.png",
        "render-front.png",
        "render-exploded.png",
        "review-iso.png",
        "review-top.png",
        "review-front.png",
        "review-exploded.png",
        *row["result"]["exports"].values(),
    }
    if filename not in allowed:
        raise HTTPException(404)
    # Preserve standard download semantics (HEAD, byte ranges and validators).
    # Do not forward arbitrary browser headers or expose other upstream routes.
    forwarded = {
        name: request.headers[name]
        for name in ("range", "if-range")
        if request.method == "GET" and name in request.headers
    }
    req = urllib.request.Request(
        ORIGIN + prefix() + f"/api/revisions/{revision}/artifacts/{filename}",
        method=request.method,
        headers=forwarded,
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            data = response.read() if request.method != "HEAD" else b""
            status = response.status
            headers = {
                name: response.headers[name]
                for name in (
                    "Content-Type",
                    "Content-Length",
                    "Content-Range",
                    "Accept-Ranges",
                    "ETag",
                    "Last-Modified",
                )
                if response.headers.get(name) is not None
            }
    except urllib.error.HTTPError as exc:
        if exc.code == 416:
            return Response(
                status_code=416,
                headers={
                    "Content-Range": exc.headers.get("Content-Range", "bytes */0"),
                    "Accept-Ranges": "bytes",
                    "X-Content-Type-Options": "nosniff",
                },
            )
        if exc.code == 400:
            raise HTTPException(400, "Invalid byte range") from exc
        if exc.code == 404:
            raise HTTPException(404, "Published file not found") from exc
        raise HTTPException(502, "Local CAD download unavailable") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise HTTPException(502, "Local CAD download unavailable") from exc
    headers.update({"X-Content-Type-Options": "nosniff", "X-CAD-Revision": revision})
    if filename not in {
        "preview.json",
        "render-iso.png",
        "render-top.png",
        "render-front.png",
        "render-exploded.png",
        "review-iso.png",
        "review-top.png",
        "review-front.png",
        "review-exploded.png",
    }:
        headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return Response(data, status_code=status, headers=headers)


@app.api_route("/downloads/sets/{asset_id}/{format_key}", methods=["GET", "HEAD"])
def named_download(asset_id: str, format_key: str, request: Request):
    if not project_id.get():
        raise HTTPException(404)
    data = upstream("/api/state").get("workspace", {})
    asset = next(
        (
            a
            for a in data.get("assets", [])
            if a["id"] == asset_id and a["role"] in ("print", "test")
        ),
        None,
    )
    if not asset:
        raise HTTPException(404, "Unknown print set")
    row = published(asset["revision"])
    if format_key == "instructions.txt":
        body = asset["note"].encode("utf-8")
        return Response(
            body if request.method == "GET" else b"",
            media_type="text/plain",
            headers={
                "Content-Disposition": 'attachment; filename="instructions.txt"',
                "Content-Length": str(len(body)),
                "X-CAD-Revision": asset["revision"],
            },
        )
    filename = row["result"]["exports"].get(format_key)
    if not filename:
        raise HTTPException(404, "Format unavailable")
    response = artifact(asset["revision"], filename, request)
    stem = re.sub(r"[^A-Za-z0-9_-]+", "-", asset["name"]).strip("-")[:65] or "part"
    suffix = re.sub(r"[^A-Za-z0-9_-]+", "-", format_key)
    response.headers["Content-Disposition"] = (
        f'attachment; filename="{stem}-{suffix}.{filename.rsplit(".", 1)[-1]}"'
    )
    return response


@app.api_route("/downloads/latest.zip", methods=["GET", "HEAD"])
def latest_download(request: Request):
    revision = upstream("/api/state")["revision"]
    if not revision:
        raise HTTPException(404, "No published model")
    row = published(revision)
    filename = row["result"]["exports"].get("zip:casting_box")
    if not filename:
        raise HTTPException(404, "Current model has no parts bundle")
    response = artifact(revision, filename, request)
    response.headers["Cache-Control"] = "no-store"
    return response


def agent_request(operation, body=None):
    secret_path = os.environ.get("CAD_AGENT_TOKEN_FILE")
    if not secret_path:
        raise HTTPException(503, "Web agent is not configured")
    secret = Path(secret_path).read_text().strip()
    origin = os.environ.get("CAD_AGENT_ORIGIN", "http://127.0.0.1:8768")
    request = urllib.request.Request(
        origin + prefix() + "/" + operation,
        data=body,
        headers={"Authorization": "Bearer " + secret, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as result:
            headers = {}
            if operation == "transcript":
                headers["Content-Disposition"] = 'attachment; filename="pi-transcript.md"'
            return Response(
                result.read(),
                status_code=result.status,
                media_type="text/plain" if operation == "transcript" else "application/json",
                headers=headers,
            )
    except urllib.error.HTTPError as exc:
        return Response(exc.read(), status_code=exc.code, media_type="application/json")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise HTTPException(503, "Web agent is unavailable") from exc


def upload_request(path, method, body=None, headers=None):
    req = urllib.request.Request(ORIGIN + prefix() + path, data=body,
                                 method=method, headers=headers or {})
    try:
        response = urllib.request.urlopen(req, timeout=60)
    except urllib.error.HTTPError as exc:
        response = exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise HTTPException(503, "Project files unavailable") from exc
    with response:
        data = response.read() if method != "HEAD" else b""
        forwarded = {name: response.headers[name] for name in (
            "Content-Type", "Content-Length", "Content-Disposition", "Content-Range",
            "Accept-Ranges", "ETag", "Last-Modified"
        ) if response.headers.get(name) is not None}
        forwarded.update({"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
        return Response(data, status_code=response.code, headers=forwarded)


@app.api_route("/api/uploads", methods=["GET", "POST"])
@app.api_route("/api/uploads/{ident}", methods=["PATCH", "DELETE"])
@app.api_route("/downloads/uploads/{ident}/file", methods=["GET", "HEAD"])
async def project_uploads(request: Request, ident: str | None = None):
    from cad.uploads import MAX_BODY

    if not project_id.get() or (ident is not None and not re.fullmatch(r"[a-f0-9]{32}", ident)):
        raise HTTPException(404)
    path = "/api/uploads" + (f"/{ident}" if ident else "")
    if request.method in ("GET", "HEAD") and ident:
        path = f"/downloads/uploads/{ident}/file"
    body = None
    headers = {k: request.headers[k] for k in ("content-type", "range", "if-range")
               if k in request.headers}
    if request.method in ("POST", "PATCH"):
        data = bytearray()
        limit = MAX_BODY if request.method == "POST" else 32768
        try:
            async with asyncio.timeout(60):
                async for chunk in request.stream():
                    if len(data) + len(chunk) > limit:
                        raise HTTPException(413, "Upload request too large")
                    data.extend(chunk)
        except TimeoutError as exc:
            raise HTTPException(408, "Upload timed out") from exc
        body = bytes(data)
    return await asyncio.to_thread(upload_request, path, request.method, body, headers)


@app.api_route("/api/projects", methods=["GET", "POST"])
async def project_catalog(request: Request):
    body = None
    if request.method == "POST":
        chunks = bytearray()
        async for chunk in request.stream():
            chunks.extend(chunk)
            if len(chunks) > 4096:
                raise HTTPException(413, "Project request too large")
        body = bytes(chunks)
    return await asyncio.to_thread(agent_request, "projects", body)


@app.api_route("/api/agent/{operation}", methods=["GET", "POST"])
async def agent_proxy(operation: str, request: Request):
    if (request.method, operation) not in {
        ("GET", "state"),
        ("GET", "transcript"),
        ("POST", "prompt"),
        ("POST", "abort"),
    }:
        raise HTTPException(404)
    body = None
    if request.method == "POST":
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > 32768:
                raise HTTPException(413, "Prompt too large")
        body = bytes(data)
    return await asyncio.to_thread(agent_request, operation, body)


@app.websocket("/api/events")
async def events(socket: WebSocket):
    await socket.accept()
    try:
        while True:
            if not app.state.gate.session(socket.scope):
                await socket.close(code=4401)
                return
            await socket.send_json(await asyncio.to_thread(state))
            await asyncio.sleep(2)
    except (WebSocketDisconnect, RuntimeError, OSError, HTTPException):
        pass


@app.get("/")
def index():
    return FileResponse(DIST / "index.html")


app.mount("/assets", StaticFiles(directory=DIST / "assets", check_dir=False), name="assets")
app.mount("/fonts", StaticFiles(directory=DIST / "fonts", check_dir=False), name="fonts")
