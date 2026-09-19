"""Read-only public demo gateway. Never tunnel the modeling service directly."""

import asyncio
import json
import re
import urllib.error
import urllib.request
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

ORIGIN = "http://127.0.0.1:8765"
DIST = Path(__file__).resolve().parent.parent / "web" / "dist"
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


def fetch(path):
    try:
        with urllib.request.urlopen(ORIGIN + path, timeout=15) as response:
            return response.read(), response.headers.get("Content-Type", "application/octet-stream")
    except (urllib.error.URLError, TimeoutError) as exc:
        raise HTTPException(502, "Local CAD service unavailable") from exc


def upstream(path):
    return json.loads(fetch(path)[0])


def published(revision):
    if not re.fullmatch(r"[a-f0-9]{32}", revision):
        raise HTTPException(404)
    state = upstream("/api/state")
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
        ORIGIN + f"/api/revisions/{revision}/artifacts/{filename}",
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


@app.websocket("/api/events")
async def events(socket: WebSocket):
    await socket.accept()
    try:
        while True:
            await socket.send_json(await asyncio.to_thread(state))
            await asyncio.sleep(2)
    except (WebSocketDisconnect, RuntimeError, OSError, HTTPException):
        pass


@app.get("/")
def index():
    return FileResponse(DIST / "index.html")


app.mount("/assets", StaticFiles(directory=DIST / "assets", check_dir=False), name="assets")
