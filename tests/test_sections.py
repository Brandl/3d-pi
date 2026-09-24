import asyncio
import json
import math

import build123d as b
import ezdxf
import numpy as np
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from cad.app import create_app
from cad.section_service import generate
from cad.sections import SectionRequest, frame, load_parts, make_section
from cad.storage import Store


def part_stats(shape):
    box = shape.bounding_box()
    return {"bounds": {"min": list(box.min), "max": list(box.max)}, "volume": shape.volume}


def test_frame_conventions_and_validation():
    for axis, normal in zip("xyz", np.eye(3)):
        f = frame(SectionRequest(axis=axis, offset=12))
        assert np.allclose(f["origin"], normal * 12)
        assert np.allclose(f["normal"], normal)
        assert np.allclose(np.cross(f["u"], f["v"]), normal)
    f = frame(SectionRequest(offset=5, tilt=(90, 0)))
    assert np.allclose(f["origin"], [0, 0, 5])
    assert np.allclose(f["normal"], [0, -1, 0])
    f = frame(SectionRequest(tilt=(30, -42)))
    matrix = np.array([f["u"], f["v"], f["normal"]])
    assert np.allclose(matrix @ matrix.T, np.eye(3))
    assert np.linalg.det(matrix) == pytest.approx(1)
    for args in ({"offset": float("nan")}, {"tilt": [0, 181]}, {"parts": []}, {"axis": "bad"}):
        with pytest.raises(ValidationError):
            SectionRequest(**args)


def test_holes_disconnected_regions_and_exact_dxf(tmp_path):
    ring = b.Box(10, 10, 10) - b.Cylinder(2, 20)
    part = b.Compound(children=[ring, b.Pos(20, 0, 0) * b.Box(2, 2, 2)])
    result = make_section({"part": part}, SectionRequest(), tmp_path, "a" * 32)
    assert result["area_sum_mm2"] == pytest.approx(104 - math.pi * 4)
    assert result["parts"][0]["regions"] == 2
    assert result["parts"][0]["holes"] == 1
    data = json.loads((tmp_path / "section.json").read_text())
    assert len(data["regions"]) == 2
    assert sum(len(r["holes"]) for r in data["regions"]) == 1
    assert (tmp_path / "section.png").read_bytes().startswith(b"\x89PNG")
    assert "<svg" in (tmp_path / "section.svg").read_text(encoding="utf-8")
    dxf = ezdxf.readfile(tmp_path / "section.dxf")
    assert dxf.units == 4  # millimetres
    assert any(e.dxftype() in ("CIRCLE", "ARC") for e in dxf.modelspace())


def test_offset_tilt_part_filter_and_empty(tmp_path):
    box = b.Box(10, 10, 10)
    result = make_section(
        {"a": box, "b": b.Pos(50, 0, 0) * box},
        SectionRequest(tilt=(30, 0), parts=["a"]),
        tmp_path / "tilt",
        "a" * 32,
    )
    assert result["area_sum_mm2"] == pytest.approx(100 / math.cos(math.radians(30)))
    assert [p["name"] for p in result["parts"]] == ["a"]
    empty = make_section({"a": box}, SectionRequest(offset=100), tmp_path / "empty", "a" * 32)
    assert empty["empty"] and empty["area_sum_mm2"] == 0
    # Origin is far away IN the plane: finite cutting face must still cover box.
    distant = make_section(
        {"a": box}, SectionRequest(offset=9999, tilt=(90, 0)), tmp_path / "distant", "a" * 32
    )
    assert distant["area_sum_mm2"] == pytest.approx(100)
    with pytest.raises(ValueError, match="Unknown output"):
        make_section({"a": box}, SectionRequest(parts=["missing"]), tmp_path / "bad", "a" * 32)


def test_step_duplicate_labels_recover_by_occurrence_not_name(tmp_path):
    a = b.Box(2, 2, 2)
    c = b.Pos(20, 0, 0) * a
    a.label = c.label = "same_prototype"
    path = tmp_path / "model.step"
    b.export_step(b.Compound(children=[a, c]), path)
    mapped = load_parts(path, {"left": part_stats(a), "right": part_stats(c)})
    assert mapped["left"].center().X == pytest.approx(0)
    assert mapped["right"].center().X == pytest.approx(20)
    with pytest.raises(ValueError, match="unambiguously"):
        load_parts(path, {"bad": {**part_stats(a), "volume": 123}, "right": part_stats(c)})


def seed(root):
    store = Store(root)
    # Seed a ready immutable revision, without a running background build.
    from cad.schema import Document

    doc = Document.model_validate(
        {
            "features": [{"name": "box", "op": "box", "size": [10, 10, 10]}],
            "outputs": [{"name": "part", "feature": "box"}],
        }
    )
    row, _ = store.create(doc.model_dump(mode="json"), 0, "section-test")
    revision = row["id"]
    folder = store.directory(revision)
    folder.mkdir(exist_ok=True)
    shape = b.Box(10, 10, 10)
    b.export_step(b.Compound(children=[shape]), folder / "model.step")
    store.update(
        revision,
        "ready",
        {
            "report": {"valid": True, "parts": {"part": part_stats(shape)}},
            "exports": {"step": "model.step"},
        },
    )
    return store, revision


def test_service_cache_busy_and_unsupported(tmp_path):
    store, revision = seed(tmp_path)

    async def exercise():
        lock = asyncio.Semaphore(1)
        await lock.acquire()
        with pytest.raises(HTTPException) as busy:
            await generate(store, revision, SectionRequest(), lock)
        assert busy.value.status_code == 429
        lock.release()
        before = store.state()
        first = await generate(store, revision, SectionRequest(), lock)
        again = await generate(store, revision, SectionRequest(), lock)
        assert first["section_id"] == again["section_id"]
        assert not first["cached"] and again["cached"]
        assert before == store.state()
        mesh, _ = store.create(store.get(revision)["document"], 0, "mesh-only-test")
        store.update(mesh["id"], "ready", {"report": {"valid": True}, "exports": {}})
        with pytest.raises(HTTPException) as unsupported:
            await generate(store, mesh["id"], SectionRequest(), lock)
        assert unsupported.value.status_code == 422

    asyncio.run(exercise())


def test_api_sections_and_downloads(tmp_path):
    # Catalog's default project uses the legacy root Store.
    store, revision = seed(tmp_path)
    with TestClient(create_app(tmp_path)) as client:
        before = client.get("/api/state").json()
        response = client.post(
            f"/api/revisions/{revision}/sections", json={"axis": "z", "offset": 0}
        )
        assert response.status_code == 200, response.text
        result = response.json()
        image = client.get(result["files"]["png"])
        assert image.status_code == 200 and image.content.startswith(b"\x89PNG")
        assert client.head(result["files"]["png"]).content == b""
        assert client.get(result["files"]["png"], headers={"Range": "bytes=0-7"}).status_code == 206
        assert (
            client.get(result["files"]["png"].replace("section.png", "input.json")).status_code
            == 404
        )
        assert (
            client.get(result["files"]["png"].replace(result["section_id"], "bad")).status_code
            == 404
        )
        assert (
            client.post(
                f"/api/revisions/{revision}/sections", json={"parts": ["unknown"]}
            ).status_code
            == 422
        )
        assert client.get("/api/state").json() == before
        other = client.post("/api/projects", json={"name": "Other sections"}).json()["id"]
        assert client.get(f"/projects/{other}" + result["files"]["png"]).status_code == 404
        assert (
            client.post(f"/projects/{other}/api/revisions/{revision}/sections", json={}).status_code
            == 404
        )
        assert not list((tmp_path / "sections").glob(".pending-*"))


def test_quota_and_interrupted_scratch_recovery(tmp_path, monkeypatch):
    from cad import section_service

    store, revision = seed(tmp_path)
    root = section_service.cache_root(store, revision)
    pending = root / ".pending-interrupted"
    pending.mkdir(parents=True)
    (pending / "worker.log").write_text("unfinished")
    section_service.recover_pending(store)
    assert not pending.exists()
    monkeypatch.setattr(section_service, "MAX_PER_REVISION", 0)
    with pytest.raises(HTTPException) as error:
        asyncio.run(generate(store, revision, SectionRequest(), asyncio.Semaphore(1)))
    assert error.value.status_code == 409
