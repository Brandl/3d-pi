"""Single-owner project catalog and request-local routing (not a tenant sandbox)."""

import json
import re
import threading
import uuid
from contextvars import ContextVar
from pathlib import Path

from starlette.responses import JSONResponse
from cad.storage import Store, Missing

project_id = ContextVar("cad_project", default=None)
VALID_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")


class ProjectScope:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        selected = None
        if scope["type"] in ("http", "websocket") and scope["path"].startswith("/projects/"):
            parts = scope["path"].split("/", 3)
            if (
                len(parts) != 4
                or not VALID_ID.fullmatch(parts[2])
                or not parts[3].startswith(("api/", "downloads/"))
            ):
                if scope["type"] == "websocket":
                    await send({"type": "websocket.close", "code": 4404})
                else:
                    await JSONResponse({"detail": "Invalid project route"}, status_code=404)(
                        scope, receive, send
                    )
                return
            selected = parts[2]
            scope = dict(
                scope,
                path="/" + parts[3],
                raw_path=("/" + parts[3]).encode(),
                cad_original_path=scope["path"],
            )
        token = project_id.set(selected)
        try:
            await self.app(scope, receive, send)
        finally:
            project_id.reset(token)


def prefix():
    selected = project_id.get()
    return f"/projects/{selected}" if selected else ""


class Catalog:
    def __init__(self, root: Path):
        self.root = root
        self.folder = root / "projects"
        self.folder.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.stores = {}
        default = self.folder / "dripper" / "project.json"
        if not default.exists():
            default.parent.mkdir(exist_ok=True)
            default.write_text(
                json.dumps({"id": "dripper", "name": "Dripper", "legacy_root": True})
            )

    def metadata(self, key):
        if not VALID_ID.fullmatch(key):
            raise Missing("Unknown project")
        path = self.folder / key / "project.json"
        if not path.is_file() or path.is_symlink() or path.parent.is_symlink():
            raise Missing("Unknown project")
        return json.loads(path.read_text())

    def list(self):
        return [
            self.metadata(p.parent.name)
            for p in sorted(self.folder.glob("*/project.json"))
            if VALID_ID.fullmatch(p.parent.name)
        ]

    def create(self, name):
        key = uuid.uuid4().hex
        directory = self.folder / key
        directory.mkdir(mode=0o700)
        Store(directory / "cad")
        value = {"id": key, "name": name, "legacy_root": False}
        temp = directory / "project.json.tmp"
        temp.write_text(json.dumps(value))
        temp.replace(directory / "project.json")
        return value

    def selected(self):
        key = project_id.get() or "dripper"
        with self.lock:
            metadata = self.metadata(key)
            if key not in self.stores:
                root = self.root if metadata.get("legacy_root") else self.folder / key / "cad"
                self.stores[key] = Store(root)
            return self.stores[key]

    def all_stores(self):
        for metadata in self.list():
            token = project_id.set(metadata["id"])
            try:
                yield self.selected()
            finally:
                project_id.reset(token)

    def __getattr__(self, name):
        return getattr(self.selected(), name)
