import json
import time
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cad.app import create_app
from cad.storage import Conflict, Store
from test_schema import box_document


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        yield client


def submit(client, document, generation=0, key=None):
    response = client.post(
        "/api/builds",
        json={
            "document": document,
            "expected_generation": generation,
            "request_key": key or uuid.uuid4().hex,
        },
    )
    assert response.status_code == 202, response.text
    return response.json()


def wait(client, revision):
    deadline = time.monotonic() + 110
    while time.monotonic() < deadline:
        row = client.get(f"/api/revisions/{revision}").json()
        if row["status"] not in ("queued", "building"):
            return row
        time.sleep(0.1)
    pytest.fail("Build did not finish")


def publish(client, revision, generation, operation="publish"):
    return client.post(
        f"/api/revisions/{revision}/{operation}", json={"expected_generation": generation}
    )


def test_full_acceptance(client):
    doc = json.loads(Path("examples/enclosure.json").read_text(encoding="utf-8"))
    first = wait(client, submit(client, doc)["id"])
    assert first["status"] == "ready", first
    assert first["result"]["report"]["valid"]
    assert publish(client, first["id"], 0).status_code == 200
    assert publish(client, first["id"], 0).json()["generation"] == 1  # idempotent retry
    assert client.get("/api/state").json()["generation"] == 1
    doc["parameters"].update(wall=3, hole_offset=10)
    second = wait(client, submit(client, doc, 1)["id"])
    assert second["status"] == "ready", second
    assert publish(client, second["id"], 1).status_code == 200
    for fmt in ("step", "stl", "3mf", "dxf?section=lid_profile"):
        response = client.get(f"/api/revisions/{second['id']}/export/{fmt}")
        assert response.status_code == 200, response.text
        artifact = client.get(response.json()["url"])
        assert artifact.status_code == 200
        assert len(artifact.content) > 100
    assert client.get(f"/api/revisions/{second['id']}/export/dxf").status_code == 422
    doc["parameters"]["wall"] = 100
    failed = wait(client, submit(client, doc, 2)["id"])
    assert failed["status"] == "failed"
    assert "cavity" in failed["result"]["error"]
    assert publish(client, failed["id"], 2).status_code == 409
    assert client.get("/api/state").json()["revision"] == second["id"]
    assert publish(client, first["id"], 2, "restore").status_code == 200
    state = client.get("/api/state").json()
    assert state["generation"] == 3
    assert state["revision"] == first["id"]
    assert len(state["history"]) == 3
    assert publish(client, second["id"], 2).status_code == 409
    assert publish(client, second["id"], 3).status_code == 409  # stale candidate, not restore


def test_gentle_twist_pipeline(client):
    doc = json.loads(Path("examples/gentle-twist.json").read_text(encoding="utf-8"))
    row = wait(client, submit(client, doc)["id"])
    assert row["status"] == "ready", row
    result = row["result"]
    assert result["report"]["valid"]
    assert result["report"]["mesh_validation"]["triangles"] == 185760
    for fmt in ("stl", "3mf"):
        assert result["report"]["export_validation"][fmt]["self_intersecting_faces"] == 0
        response = client.get(f"/api/revisions/{row['id']}/export/{fmt}")
        assert response.status_code == 200
        artifact = client.get(response.json()["url"])
        assert artifact.status_code == 200
        if fmt == "stl":
            assert len(artifact.content) == 84 + 185760 * 50
    assert client.get(f"/api/revisions/{row['id']}/export/step").status_code == 422
    assert client.get(f"/api/revisions/{row['id']}/artifacts/validation.json").status_code == 200
    assert publish(client, row["id"], 0).status_code == 200


def test_casting_box_named_exports(client):
    doc = json.loads(Path("examples/gentle-twist-casting-box.json").read_text(encoding="utf-8"))
    row = wait(client, submit(client, doc)["id"])
    assert row["status"] == "ready", row
    assert len(row["result"]["report"]["parts"]) == 5
    assert row["result"]["report"]["parameters"]["twist_degrees"] == 40
    for fmt, part in (
        ("stl", "wall_left"),
        ("3mf", "lock_front"),
        ("step", "casting_box"),
        ("zip", "casting_box"),
    ):
        response = client.get(f"/api/revisions/{row['id']}/export/{fmt}?part={part}")
        assert response.status_code == 200, response.text
        artifact = client.get(response.json()["url"])
        assert artifact.status_code == 200
        if fmt == "zip":
            head = client.head(response.json()["url"])
            assert head.status_code == 200 and head.content == b""
            assert int(head.headers["content-length"]) == len(artifact.content)
            partial = client.get(response.json()["url"], headers={"Range": "bytes=0-15"})
            assert partial.status_code == 206 and partial.content == artifact.content[:16]
    assert client.get(f"/api/revisions/{row['id']}/export/step").status_code == 422
    assert client.get(f"/api/revisions/{row['id']}/export/stl?part=unknown").status_code == 422
    assert publish(client, row["id"], 0).status_code == 200


def test_failing_checks_cannot_publish_or_export(client):
    doc = box_document()
    doc["checks"][0]["expected"] = 999
    row = wait(client, submit(client, doc)["id"])
    assert row["status"] == "ready", row
    assert not row["result"]["report"]["valid"]
    assert publish(client, row["id"], 0).status_code == 409
    assert client.get(f"/api/revisions/{row['id']}/export/stl").status_code == 409
    assert client.get(f"/api/revisions/{row['id']}/artifacts/model.stl").status_code == 404


def test_cancel_and_idempotency(client):
    first = submit(client, box_document(), key="same-key")
    retry = submit(client, box_document(), key="same-key")
    assert retry["id"] == first["id"]
    doc = box_document()
    doc["name"] = "different"
    response = client.post(
        "/api/builds", json={"document": doc, "expected_generation": 0, "request_key": "same-key"}
    )
    assert response.status_code == 409
    assert client.post(f"/api/revisions/{first['id']}/cancel").status_code == 200
    assert client.get(f"/api/revisions/{first['id']}").json()["status"] == "cancelled"
    assert client.get("/api/state").json()["revision"] is None


def test_boundaries(client):
    assert client.get("/api/state", headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.get("/api/state", headers={"Host": "evil.example"}).status_code == 400
    assert client.get("/api/revisions/missing").status_code == 404
    assert client.post("/api/builds", content=b"x" * (256 * 1024 + 1)).status_code == 413
    assert client.post("/api/builds", json={"python": "anything"}).status_code == 422
    assert client.get("/api/schema").json()["properties"]["schema_version"]


def test_websocket_snapshot(client):
    with client.websocket_connect("/api/events") as socket:
        assert socket.receive_json()["generation"] == 0


def test_restart_preserves_publication_and_recovers_jobs(tmp_path):
    store = Store(tmp_path)
    first, _ = store.create(box_document(), 0, "first")
    store.update(first["id"], "ready", {"report": {"valid": True}})
    store.publish(first["id"], 0)
    pending, _ = store.create(box_document(), 1, "pending")
    with TestClient(create_app(tmp_path)) as client:
        assert client.get("/api/state").json()["revision"] == first["id"]
        assert client.get(f"/api/revisions/{pending['id']}").json()["status"] == "failed"
    with pytest.raises(Conflict):
        store.create(box_document(), 0, "stale")


def test_queue_limit_and_stale_candidates(tmp_path):
    store = Store(tmp_path)
    revisions = [store.create(box_document(), 0, f"request-{i}")[0] for i in range(4)]
    with pytest.raises(Conflict, match="queue is full"):
        store.create(box_document(), 0, "fifth")
    for row in revisions[:2]:
        store.update(row["id"], "ready", {"report": {"valid": True}})
    store.publish(revisions[0]["id"], 0)
    with pytest.raises(Conflict, match="older generation"):
        store.publish(revisions[1]["id"], 1)
    with pytest.raises(Conflict, match="previously published"):
        store.publish(revisions[1]["id"], 1, restore=True)


def test_worker_crash_is_contained(client, monkeypatch):
    class CrashedProcess:
        returncode = 137

        async def wait(self):
            return self.returncode

    async def crash(*args, **kwargs):
        return CrashedProcess()

    monkeypatch.setattr("cad.app.asyncio.create_subprocess_exec", crash)
    row = wait(client, submit(client, box_document())["id"])
    assert row["status"] == "failed"
    assert "137" in row["result"]["error"]
    assert client.get("/api/state").json()["revision"] is None


def test_artifact_allowlist(client):
    row = wait(client, submit(client, box_document())["id"])
    assert row["status"] == "ready", row
    assert client.get(f"/api/revisions/{row['id']}/artifacts/worker.log").status_code == 404
    assert client.get(f"/api/revisions/{row['id']}/artifacts/manifest.json").status_code == 200
