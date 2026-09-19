import json
from pathlib import Path

from fastapi.testclient import TestClient

from cad.app import create_app
from cad import preview
from cad.auth import COOKIE, PasswordGate
from cad.introspection import component, tree
from cad.limits import CASTING_BOX_LIMITS
from cad.storage import Store


def document(name="origami-20-locking-base"):
    return json.loads(Path(f"examples/{name}.json").read_text(encoding="utf-8"))


def flatten(node):
    return [node, *(item for child in node["children"] for item in flatten(child))]


def test_tree_has_unique_parts_features_and_registered_interfaces():
    row = {
        "id": "a" * 32,
        "status": "failed",
        "document": document(),
        "result": {"error": "example failure"},
    }
    result = tree(row)
    nodes = flatten(result["root"])
    ids = {node["id"] for node in nodes}
    assert len(ids) == len(nodes)
    assert len([node for node in nodes if node["kind"] == "part"]) == 5
    assert "joint:captured_floor" in ids
    assert "interface:wall_left:front_rail" in ids
    for node in nodes:
        assert set(node.get("members", []) + node.get("depends_on", [])) <= ids
    detail = component(row, "joint:slide_lock_front")
    assert detail["parameters"]["lock_clearance"]["expression"] == 0.15
    assert detail["parameters"]["lock_clearance"]["resolved"] is None
    assert detail["measurements"] is None
    assert "part:wall_left" in detail["parameters"]["lock_clearance"]["used_by"]
    assert tree(row) == result  # Read-only and deterministic even for a failed build.


def test_generic_feature_dag_preserves_dependencies():
    row = {"id": "b" * 32, "status": "queued", "document": document("enclosure")}
    nodes = flatten(tree(row)["root"])
    assert not any(node["kind"] == "mating_relationship" for node in nodes)
    outputs = {n["output_name"]: n for n in nodes if n["kind"] == "part"}
    assert "wall" in outputs["enclosure"]["parameter_keys"]
    assert outputs["enclosure"]["depends_on"]


def test_tree_api_and_published_gateway_ownership(tmp_path, monkeypatch):
    store = Store(tmp_path)
    first, _ = store.create(document(), 0, "first")
    store.update(first["id"], "ready", {"report": {"valid": True}, "exports": {}})
    store.publish(first["id"], 0)
    candidate, _ = store.create(document(), 1, "candidate")
    store.update(candidate["id"], "failed", {"error": "not published"})
    with TestClient(create_app(tmp_path)) as client:
        assert (
            client.get("/api/capabilities").json()["casting_box_limits_mm"]["top_clearance"]["max"]
            == CASTING_BOX_LIMITS["top_clearance"][1]
            == 60
        )
        assert client.get(f"/api/revisions/{candidate['id']}/tree").status_code == 200
        assert (
            client.get(f"/api/revisions/{first['id']}/components/part:wall_left").status_code == 200
        )
        assert (
            client.get(f"/api/revisions/{first['id']}/components/no-such-node").status_code == 404
        )

    def upstream(path):
        return store.state() if path == "/api/state" else store.get(path.rsplit("/", 1)[-1])

    monkeypatch.setattr(preview, "upstream", upstream)
    gate = PasswordGate({"salt": "00" * 16, "hash": "00" * 64})
    monkeypatch.setattr(preview.app.state, "gate", gate)
    token, _ = gate.issue()
    with TestClient(preview.app, base_url="https://testserver", cookies={COOKIE: token}) as client:
        expected = tree(store.get(first["id"]))
        assert client.get(f"/api/revisions/{first['id']}/tree").json() == expected
        assert client.get(f"/api/revisions/{candidate['id']}/tree").status_code == 404
        assert (
            client.get(f"/api/revisions/{candidate['id']}/components/part:wall_left").status_code
            == 404
        )
        assert (
            client.get(f"/api/revisions/{first['id']}/components/no-such-node").status_code == 404
        )
    with TestClient(preview.app, base_url="https://testserver") as client:
        assert client.get(f"/api/revisions/{first['id']}/tree").status_code == 401
    assert store.state()["generation"] == 1
