import importlib.util
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cad.app import create_app
from cad.projects import project_id
from cad.storage import Store
from test_schema import box_document


def ready(store, key="same-key"):
    row, _ = store.create(box_document(), 0, key)
    store.update(
        row["id"],
        "ready",
        {"report": {"valid": True, "parts": {}}, "exports": {"stl": "model.stl"}},
    )
    store.directory(row["id"]).mkdir()
    (store.directory(row["id"]) / "model.stl").write_bytes(b"isolated artifact")
    return row["id"]


def test_project_scope_and_generation_isolation(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        keys = [
            client.post("/api/projects", json={"name": name}).json()["id"] for name in ("A", "B")
        ]
        ids = []
        for key in keys:
            token = project_id.set(key)
            try:
                ids.append(ready(app.state.catalog.selected()))
            finally:
                project_id.reset(token)
        for i, key in enumerate(keys):
            base = f"/projects/{key}"
            assert client.get(base + "/api/state").json()["generation"] == 0
            assert client.get(base + f"/api/revisions/{ids[1 - i]}").status_code == 404
            assert client.get(base + f"/downloads/{ids[1 - i]}/model.stl").status_code == 404
            assert (
                client.post(
                    base + f"/api/revisions/{ids[1 - i]}/publish", json={"expected_generation": 0}
                ).status_code
                == 404
            )
            assert (
                client.post(
                    base + f"/api/revisions/{ids[i]}/publish", json={"expected_generation": 0}
                ).status_code
                == 200
            )
            assert client.get(base + "/api/state").json()["generation"] == 1
            assert (
                client.get(base + f"/downloads/{ids[i]}/model.stl").content == b"isolated artifact"
            )
        assert client.get("/api/state").json()["generation"] == 0
        assert client.get("/projects/unknown/api/state").status_code == 404
        assert client.get("/projects/bad.name/api/state").status_code == 404
        assert client.post("/api/projects", json={"name": " "}).status_code == 422
        with client.websocket_connect(f"/projects/{keys[0]}/api/events") as ws:
            assert ws.receive_json()["revision"] == ids[0]
    # Reopen the catalog and retain independent publications.
    with TestClient(create_app(tmp_path)) as client:
        assert client.get(f"/projects/{keys[1]}/api/state").json()["revision"] == ids[1]


def test_copy_only_folder_migration(tmp_path):
    script = Path(__file__).resolve().parent.parent / "scripts/migrate-project-folders.py"
    if not script.is_file():
        pytest.skip("Installation-specific migration utility is not in the source archive")
    spec = importlib.util.spec_from_file_location("migrate_projects", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    runtime = tmp_path / "runtime"
    store = Store(runtime / "cad")
    first = ready(store)
    store.publish(first, 0)
    doc = box_document()
    doc["name"] = "B-01 Bike basket twist-lock test"
    second, _ = store.create(doc, 1, "twist-key")
    store.update(second["id"], "ready", {"report": {"valid": True}, "exports": {}})
    store.directory(second["id"]).mkdir()
    (store.directory(second["id"]) / "preview.json").write_text("{}")
    sessions = runtime / "agent" / "sessions"
    sessions.mkdir(parents=True)
    original = '{"type":"message","message":{"role":"user","content":"Shared design history"}}\n'
    (sessions / "original.jsonl").write_text(original)
    (runtime / "agent" / "requests.json").write_text("[]")
    source = tmp_path / "source"
    design = source / "designs" / "bike-basket-twistlock"
    design.mkdir(parents=True)
    (design / "document.json").write_text(json.dumps(doc))
    before = store.state()
    module.migrate(runtime, source)
    assert store.state() == before
    assert (sessions / "original.jsonl").read_text() == original
    for key in ("dripper", "bike-basket-twistlock"):
        folder = runtime / "projects" / key
        assert (folder / "pi/legacy-shared/original.jsonl").read_text() == original
        assert (folder / "cad/project.sqlite3").is_file()
        assert (folder / "source/.git").is_dir()
    migrated = Store(runtime / "cad/projects/dripper/cad")
    assert migrated.state() == before
    twist = Store(runtime / "cad/projects/bike-basket-twistlock/cad")
    assert twist.state()["generation"] == 0
    assert twist.state()["publications"] == []
    assert twist.get(second["id"]) == store.get(second["id"])
    with pytest.raises(RuntimeError, match="already exist"):
        module.migrate(runtime, source)
