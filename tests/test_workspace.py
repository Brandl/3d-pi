import copy
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from cad.app import create_app
from cad.schema import Document
from cad.storage import Store, Conflict
from cad.workspace import CommitRequest, AssetRequest, commit, attach
from test_schema import box_document


def ready(store, length=10):
    doc = box_document()
    doc["name"] = f"Box {length}"
    normalized = Document.model_validate(doc).model_dump()
    row, _ = store.create(normalized, store.state()["generation"], uuid.uuid4().hex)
    store.update(row["id"], "ready", {"report": {"valid": True}, "exports": {"stl": "model.stl"}})
    return row


def request(row, **changes):
    return CommitRequest.model_validate(
        dict(
            revision=row["id"],
            base_revision=None,
            expected_generation=0,
            request_key=uuid.uuid4().hex,
            name="Create enclosure",
            icon="📦",
            source_commit="a" * 40,
            source_file="document.json",
            source_document=row["document"],
            **changes,
        )
    )


def test_explicit_head_assets_idempotency_and_persistence(tmp_path):
    store = Store(tmp_path)
    first = ready(store)
    assert store.state()["workspace"]["revision"] is None
    req = request(first)
    committed = commit(store, req)
    assert commit(store, req)["id"] == committed["id"]
    with pytest.raises(Conflict):
        commit(store, req.model_copy(update={"name": "Different name"}))
    newer = ready(store, 20)
    attachment = AssetRequest(
        commit=committed["id"],
        revision=newer["id"],
        role="test",
        name="Return test",
        note="Fixture only",
        request_key="test-fixture-key",
    )
    asset = attach(store, attachment)
    assert attach(store, attachment)["id"] == asset["id"]
    assert store.state()["workspace"]["revision"] == first["id"]
    assert len(store.state()["workspace"]["commits"]) == 1
    assert store.state()["generation"] == 0
    assert store.state()["publications"] == []
    reloaded = Store(tmp_path).state()["workspace"]
    assert reloaded["assets"][0]["role"] == "test"
    assert reloaded["commits"][0]["name"] == "Create enclosure"
    assert reloaded["commits"][0]["icon"] == "📦"
    bad = request(newer).model_copy(update={"base_revision": first["id"], "expected_generation": 1})
    with pytest.raises(Conflict, match="related output"):
        commit(store, bad)


def test_legacy_default_fields_compare_without_rewriting_history(tmp_path):
    store = Store(tmp_path)
    doc = box_document()  # intentionally unnormalized historical schema-v1 record
    row, _ = store.create(doc, 0, "legacy-default-fields")
    store.update(row["id"], "ready", {"report": {"valid": True}, "exports": {}})
    original = copy.deepcopy(store.get(row["id"]))
    committed = commit(store, request(row))
    assert committed["document_hash"] == original["content_hash"]
    assert store.get(row["id"]) == original
    assert store.state()["workspace"]["revision"] == row["id"]


def test_stale_mismatched_invalid_and_unchanged(tmp_path):
    store = Store(tmp_path)
    first = ready(store)
    req = request(first)
    altered = copy.deepcopy(first["document"])
    altered["name"] = "Wrong source"
    with pytest.raises(Conflict, match="does not match"):
        commit(store, req.model_copy(update={"source_document": Document.model_validate(altered)}))
    commit(store, req)
    with pytest.raises(Conflict, match="changed"):
        commit(store, request(first))
    with pytest.raises(Conflict, match="No design change"):
        commit(
            store,
            request(first).model_copy(
                update={"base_revision": first["id"], "expected_generation": 1}
            ),
        )
    candidate, _ = store.create(first["document"], 0, uuid.uuid4().hex)
    with pytest.raises(Conflict, match="ready"):
        commit(
            store,
            request(candidate).model_copy(
                update={"base_revision": first["id"], "expected_generation": 1}
            ),
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("name", ""),
        ("name", "bad\nname"),
        ("icon", "box"),
        ("icon", "+"),
        ("icon", "<svg>"),
        ("icon", "\u202e📦"),
        ("source_file", "../secret"),
        ("source_file", "/tmp/source"),
        ("source_commit", "a" * 41),
    ],
)
def test_metadata_validation(tmp_path, field, value):
    row = ready(Store(tmp_path))
    data = request(row).model_dump()
    data[field] = value
    with pytest.raises(ValidationError):
        CommitRequest.model_validate(data)


@pytest.mark.parametrize("icon", ["↔️", "🛠️", "👩🏽‍🔧", "🔒"])
def test_unicode_icons(tmp_path, icon):
    data = request(ready(Store(tmp_path))).model_dump()
    data["icon"] = icon
    assert CommitRequest.model_validate(data).icon == icon


def test_concurrent_commits_only_one_wins(tmp_path):
    store = Store(tmp_path)
    a, b = ready(store), ready(store, 20)

    def attempt(row):
        try:
            return commit(store, request(row))["revision"]
        except Conflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, [a, b]))
    assert results.count("conflict") == 1
    assert store.state()["workspace"]["generation"] == 1


def test_scoped_api_preserves_legacy_and_rejects_cross_project(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        base = app.state.store
        row = ready(base)
        base.publish(row["id"], 0)
        other = client.post("/api/projects", json={"name": "Other"}).json()["id"]
        payload = request(row).model_dump()
        payload["base_revision"] = row["id"]
        assert client.post(
            f"/projects/{other}/api/workspace/commits", json=payload
        ).status_code in (404, 409)
        response = client.post("/api/workspace/commits", json=payload)
        assert response.status_code == 201, response.text
        data = client.get("/api/state").json()
        assert data["generation"] == 1 and len(data["publications"]) == 1
        assert data["workspace"]["generation"] == 1
        assert client.get(f"/projects/{other}/api/state").json()["workspace"]["generation"] == 0
        missing = dict(payload)
        del missing["icon"]
        assert client.post("/api/workspace/commits", json=missing).status_code == 422
