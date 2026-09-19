import asyncio
import fcntl
import json
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from pydantic import Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from cad.schema import Document, Strict
from cad.storage import Conflict, Missing, Store

ROOT = Path(__file__).resolve().parent.parent


class BuildRequest(Strict):
    document: Document
    expected_generation: int = Field(ge=0)
    request_key: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")


class PublishRequest(Strict):
    expected_generation: int = Field(ge=0)


def same_origin(origin, host):
    if not origin:
        return True
    parsed = urlparse(origin)
    return parsed.scheme in ("http", "https") and parsed.netloc == host


def create_app(data_dir: Path | None = None):
    store = Store((data_dir or Path(os.environ.get("CAD_DATA_DIR", ROOT / "data"))).resolve())
    tasks = {}
    processes = {}
    subscribers = set()
    semaphore = asyncio.Semaphore(1)

    def notify():
        for queue in tuple(subscribers):
            if queue.empty():
                queue.put_nowait(True)

    async def run_build(revision):
        try:
            async with semaphore:
                if store.get(revision)["status"] != "queued":
                    return
                store.update(revision, "building")
                notify()
                directory = store.directory(revision)
                directory.mkdir(exist_ok=True)
                (directory / "document.json").write_text(
                    json.dumps(store.get(revision)["document"])
                )
                # Whitelisted environment: credentials and pi session metadata are not inherited.
                env = {
                    "PATH": os.path.dirname(sys.executable) + ":/usr/bin:/bin",
                    "HOME": str(directory),
                    "MPLCONFIGDIR": str(directory / ".mpl"),
                    "PYTHONPATH": str(ROOT),
                    "OPENBLAS_NUM_THREADS": "1",
                    "OMP_NUM_THREADS": "1",
                    "LANG": "C.UTF-8",
                }
                with (directory / "worker.log").open("wb") as log:
                    proc = await asyncio.create_subprocess_exec(
                        sys.executable,
                        "-m",
                        "cad.worker",
                        str(directory),
                        cwd=directory,
                        env=env,
                        stdout=log,
                        stderr=log,
                    )
                    processes[revision] = proc
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=100)
                    except TimeoutError:
                        proc.kill()
                        await proc.wait()
                        raise ValueError("Build exceeded 100 second deadline")
                result_file = directory / "result.json"
                if proc.returncode != 0 or not result_file.exists():
                    raise ValueError(
                        f"Geometry worker exited unexpectedly (code {proc.returncode})"
                    )
                result = json.loads(result_file.read_text(encoding="utf-8"))
                result["revision"] = revision
                result["content_hash"] = store.get(revision)["content_hash"]
                (directory / "manifest.json").write_text(json.dumps(result, indent=2))
                store.update(revision, result["status"], result)
        except asyncio.CancelledError:
            proc = processes.get(revision)
            if proc and proc.returncode is None:
                proc.kill()
                await proc.wait()
            store.update(revision, "cancelled", {"error": "Build cancelled"})
            raise
        except Exception as exc:
            store.update(revision, "failed", {"error": str(exc)[:4000]})
        finally:
            processes.pop(revision, None)
            tasks.pop(revision, None)
            notify()

    @asynccontextmanager
    async def lifespan(_app):
        lock = (store.root / "service.lock").open("a")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lock.close()
            raise RuntimeError("Another CAD service is using this data directory")
        store.recover()
        try:
            yield
        finally:
            pending = list(tasks.values())
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            lock.close()

    app = FastAPI(title="3d-pi", version="0.1.0", lifespan=lifespan)
    app.state.store = store
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"]
    )

    @app.middleware("http")
    async def local_boundary(request: Request, call_next):
        if not same_origin(request.headers.get("origin"), request.headers.get("host")):
            return JSONResponse(
                {"detail": "Cross-origin requests are not allowed"}, status_code=403
            )
        if request.method in ("POST", "PUT", "PATCH"):
            # Bound streamed requests as well as those with Content-Length.
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > 256 * 1024:
                    return JSONResponse({"detail": "Request exceeds 256 KiB"}, status_code=413)
            request._body = bytes(body)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_request, exc):
        # Do not echo untrusted input (including non-finite numbers) into JSON errors.
        errors = [{key: error[key] for key in ("loc", "type", "msg")} for error in exc.errors()]
        return JSONResponse({"detail": errors}, status_code=422)

    @app.exception_handler(Conflict)
    async def conflict(_request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(Missing)
    async def missing(_request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @app.get("/api/health")
    def health():
        return {"status": "ok", "mode": "local-only", "schema_version": 1}

    @app.get("/api/schema")
    def schema():
        return Document.model_json_schema()

    @app.get("/api/example")
    def example():
        return json.loads((ROOT / "examples" / "enclosure.json").read_text(encoding="utf-8"))

    @app.get("/api/state")
    def state():
        return store.state()

    @app.get("/api/revisions/{revision}")
    def inspect(revision: str):
        return store.get(revision)

    @app.post("/api/builds", status_code=202)
    async def build(request: BuildRequest):
        row, created = store.create(
            request.document.model_dump(), request.expected_generation, request.request_key
        )
        if created:
            task = asyncio.create_task(run_build(row["id"]))
            tasks[row["id"]] = task
            notify()
        return row

    @app.post("/api/revisions/{revision}/cancel")
    async def cancel(revision: str):
        row = store.get(revision)
        if row["status"] not in ("queued", "building"):
            raise Conflict("Build is already finished")
        store.update(revision, "cancelled", {"error": "Build cancelled"})
        task = tasks.get(revision)
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        tasks.pop(revision, None)
        notify()
        return store.get(revision)

    @app.post("/api/revisions/{revision}/{operation}")
    async def publish(
        revision: str, operation: Literal["publish", "restore"], request: PublishRequest
    ):
        result = store.publish(
            revision, request.expected_generation, restore=operation == "restore"
        )
        notify()
        return result

    @app.get("/api/revisions/{revision}/report")
    def report(revision: str):
        row = store.get(revision)
        if row["status"] != "ready":
            raise Conflict("Build is not ready")
        return {"revision": revision, **row["result"]["report"]}

    @app.get("/api/revisions/{revision}/export/{fmt}")
    def export(
        revision: str,
        fmt: Literal["step", "stl", "3mf", "dxf", "zip"],
        section: str | None = None,
        part: str | None = None,
    ):
        row = store.get(revision)
        if row["status"] != "ready" or not row["result"]["report"]["valid"]:
            raise Conflict("Export requires a ready revision with passing checks")
        key = f"dxf:{section}" if fmt == "dxf" else f"{fmt}:{part}" if part else fmt
        filename = row["result"]["exports"].get(key)
        if not filename:
            raise HTTPException(
                422, "Format unavailable for this model, or DXF section name missing"
            )
        return {
            "revision": revision,
            "units": "mm",
            "filename": filename,
            "url": f"/api/revisions/{revision}/artifacts/{filename}",
            "manifest_url": f"/api/revisions/{revision}/artifacts/manifest.json",
        }

    @app.api_route("/api/revisions/{revision}/artifacts/{filename}", methods=["GET", "HEAD"])
    @app.api_route("/downloads/{revision}/{filename}", methods=["GET", "HEAD"])
    def artifact(revision: str, filename: str):
        row = store.get(revision)
        if row["status"] != "ready":
            raise Conflict("Build is not ready")
        allowed = {
            "preview.json",
            "document.json",
            "manifest.json",
            "render-iso.png",
            "render-top.png",
            "render-front.png",
            "render-exploded.png",
            "validation.json",
            "casting-box-report.json",
        }
        if row["result"]["report"]["valid"]:
            allowed.update(row["result"]["exports"].values())
        if filename not in allowed:
            raise Missing("Artifact not found")
        path = store.directory(revision) / filename
        if not path.is_file():
            raise Missing("Artifact missing from disk")
        media = "image/png" if filename.endswith(".png") else None
        disposition = "inline" if filename.endswith((".png", ".json")) else "attachment"
        return FileResponse(
            path, media_type=media, filename=filename, content_disposition_type=disposition
        )

    @app.websocket("/api/events")
    async def events(socket: WebSocket):
        if not same_origin(socket.headers.get("origin"), socket.headers.get("host")):
            await socket.close(code=1008)
            return
        await socket.accept()
        queue = asyncio.Queue(maxsize=1)
        subscribers.add(queue)
        try:
            while True:
                await socket.send_json(store.state())
                try:
                    await asyncio.wait_for(queue.get(), timeout=10)
                except TimeoutError:
                    pass  # Periodic full snapshots also recover missed events.
        except (WebSocketDisconnect, RuntimeError, OSError):
            pass
        finally:
            subscribers.discard(queue)

    dist = ROOT / "web" / "dist"
    if dist.exists():
        app.mount("/", StaticFiles(directory=dist, html=True), name="viewer")
    else:

        @app.get("/")
        def missing_viewer():
            return JSONResponse({"detail": "Run npm ci && npm run build in web/"}, status_code=503)

    return app
