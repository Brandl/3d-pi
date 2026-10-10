"""Feed eligibility/order tests with synthetic build reports, not kernel certification."""

import uuid

from cad.storage import Store
from cad.workspace import AssetRequest, attach, commit
from test_workspace import ready, request


def pending(store, name):
    document = ready_document()
    document["name"] = name
    return store.create(document, store.state()["generation"], uuid.uuid4().hex)[0]


def ready_document():
    from cad.schema import Document
    from test_schema import box_document

    return Document.model_validate(box_document()).model_dump()


def test_only_changed_passing_unregistered_builds_stream(tmp_path):
    store = Store(tmp_path)
    ready(store, 5)  # An older experiment must not become a live preview.
    first = ready(store)
    saved = commit(store, request(first))
    baseline = store.state()
    ready(store)  # Identical document to saved head, even with a new build ID.
    good = ready(store, 20)
    for status, valid in (("failed", True), ("ready", False), ("ready", None)):
        row = pending(store, f"Excluded {status} {valid}")
        store.update(row["id"], status, {"report": {"valid": valid}})
    pending(store, "Still queued")
    state = store.state()
    assert [r["revision"] for r in state["intermediates"]] == [good["id"]]
    assert state["workspace"] == baseline["workspace"]
    assert state["publications"] == [] and state["generation"] == 0
    assert state["event_sequence"] > baseline["event_sequence"]
    assert any(r["valid"] is False for r in state["history"])
    attach(
        store,
        AssetRequest(
            commit=saved["id"],
            revision=good["id"],
            role="print",
            name="Named print",
            request_key="attach-print-output",
        ),
    )
    assert store.state()["intermediates"] == []
    assert store.state()["event_sequence"] > state["event_sequence"]


def test_commit_supersedes_previews_without_deleting_builds(tmp_path):
    store = Store(tmp_path)
    first = ready(store)
    commit(store, request(first))
    other = ready(store, 15)
    late = pending(store, "Started before save")
    good = ready(store, 20)
    before = store.state()
    commit(
        store,
        request(good).model_copy(update={"expected_generation": 1, "base_revision": first["id"]}),
    )
    store.update(late["id"], "ready", {"report": {"valid": True}})
    after = store.state()
    assert after["intermediates"] == []
    assert after["workspace"]["revision"] == good["id"]
    assert other["id"] in after["candidates"]
    assert store.get(other["id"])["status"] == "ready"
    assert after["event_sequence"] > before["event_sequence"]
    assert Store(tmp_path).state()["event_sequence"] == after["event_sequence"]
    newer = ready(store, 30)
    assert [r["revision"] for r in store.state()["intermediates"]] == [newer["id"]]


def test_feed_is_bounded_and_chronological(tmp_path):
    store = Store(tmp_path)
    ids = [ready(store, i)["id"] for i in range(40)]
    state = store.state()
    assert [r["revision"] for r in state["intermediates"]] == ids[-32:]
    # Reads/reinitialization are not changes and cannot move the cursor.
    assert Store(tmp_path).state()["event_sequence"] == state["event_sequence"]


def test_failures_do_not_age_the_last_good_preview_out_of_the_feed(tmp_path):
    store = Store(tmp_path)
    good = ready(store)
    for i in range(102):
        row, _ = store.create({"name": f"Failed {i}"}, 0, uuid.uuid4().hex)
        store.update(row["id"], "failed")
    state = store.state()
    assert good["id"] not in {row["id"] for row in state["history"]}
    assert [row["revision"] for row in state["intermediates"]] == [good["id"]]
    assert good["id"] in state["candidates"]
    assert state["candidate_names"][good["id"]] == good["document"]["name"]


def test_legacy_publication_is_a_preview_watermark(tmp_path):
    store = Store(tmp_path)
    ready(store, 5)
    first = ready(store)
    store.publish(first["id"], 0)
    assert store.state()["intermediates"] == []
    good = ready(store, 20)
    assert [r["revision"] for r in store.state()["intermediates"]] == [good["id"]]
