from fastapi.testclient import TestClient

from cad import preview
from cad.storage import Store


def ready(store, name, generation, key):
    row, _ = store.create({"name": name, "parameters": {"not_public": 123}}, generation, key)
    store.update(row["id"], "ready", {"report": {"valid": True}})
    return row["id"]


def test_publication_timeline_is_complete_and_does_not_leak_candidates(tmp_path, monkeypatch):
    store = Store(tmp_path)
    first = ready(store, "First design", 0, "one")
    store.publish(first, 0)
    second = ready(store, "Second design", 1, "two")
    store.publish(second, 1)
    candidate = ready(store, "PRIVATE candidate", 2, "private")
    for generation in range(2, 106):
        store.publish(first if generation % 2 == 0 else second, generation, restore=True)
    state = store.state()
    assert len(state["publications"]) == 106
    assert state["publications"][-1]["name"] == "First design"
    assert state["publications"][-1]["generation"] == 1
    assert state["publications"][0]["operation"] == "restore"
    assert candidate not in {p["revision"] for p in state["publications"]}
    assert all("document" not in p and "not_public" not in p for p in state["publications"])

    def upstream(path):
        if path == "/api/state":
            return store.state()
        return store.get(path.rsplit("/", 1)[1])

    monkeypatch.setattr(preview, "upstream", upstream)
    with TestClient(preview.app) as client:
        response = client.get("/api/state")
        assert response.status_code == 200
        data = response.json()
        assert len(data["publications"]) == 106
        assert "PRIVATE" not in response.text and candidate not in response.text
        assert "not_public" not in response.text and "document" not in response.text
        assert client.get(f"/api/revisions/{candidate}").status_code == 404
        # Published revisions remain allowed even beyond the former 100-event cutoff.
        assert preview.published(first)["id"] == first
    assert store.state()["generation"] == 106
