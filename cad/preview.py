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
    if project_id.get() and any(
        r["id"] == revision and r["status"] == "ready" for r in state["history"]
    ):
        return upstream(f"/api/revisions/{revision}")
    if revision not in {p["revision"] for p in state["publications"]}:
        raise HTTPException(404, "Only published models are available in the preview")
    return upstream(f"/api/revisions/{revision}")


@app.get("/api/state")
def state():
    data = upstream("/api/state")
    # Do not disclose unpublished build history, failures, or source documents.
    return {
        "revision": data["revision"],
        "generation": data["generation"],
        "candidates": [
            r["id"]
            for r in data["history"]
            if r["status"] == "ready"
            and r["id"] not in {p["revision"] for p in data["publications"]}
        ]
        if project_id.get()
        else [],
        "history": [{"id": data["revision"], "status": "ready"}] if data["revision"] else [],
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
