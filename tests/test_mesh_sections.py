import asyncio
import copy
import json

import build123d as b
import ezdxf
import numpy as np
import pytest

from cad.mesh_sections import make_mesh_section
from cad.sections import SectionRequest
from cad.section_service import generate
from test_sections import part_stats, seed


def preview(path, shapes):
    parts = []
    for name, shape in shapes.items():
        vertices, triangles = shape.tessellate(0.01, 0.1)
        parts.append(
            {"name": name, "vertices": [list(v) for v in vertices], "triangles": triangles}
        )
    path.write_text(json.dumps({"units": "mm", "parts": parts}))
    return {name: part_stats(shape) for name, shape in shapes.items()}


def test_mesh_holes_islands_and_explicit_basis(tmp_path):
    # Generic rectangular annulus + separate island: exact polygonal test,
    # independent of any excluded private designs.
    ring = b.Box(12, 12, 8) - b.Box(6, 6, 12)
    shape = b.Compound(children=[ring, b.Pos(25, 0, 0) * b.Box(2, 2, 2)])
    path = tmp_path / "preview.json"
    measurements = preview(path, {"part": shape})
    summary = make_mesh_section(
        path, measurements, SectionRequest(representation="mesh"), tmp_path / "out", "a" * 32
    )
    assert summary["representation"] == "mesh"
    assert summary["area_sum_mm2"] == pytest.approx(112)
    assert summary["parts"][0]["regions"] == 2
    assert summary["parts"][0]["holes"] == 1
    dxf = ezdxf.readfile(tmp_path / "out/section.dxf")
    assert dxf.units == 4
    assert len(list(dxf.modelspace())) == 3
    assert all(e.dxftype() == "LWPOLYLINE" and e.closed for e in dxf.modelspace())
    data = json.loads((tmp_path / "out/section.json").read_text())
    assert len(data["regions"]) == 2
    assert "APPROXIMATE MESH" in (tmp_path / "out/section.svg").read_text(encoding="utf-8")


def test_mesh_world_frame_tilt_filter_empty_and_invalid(tmp_path):
    box = b.Pos(20, 0, 10) * b.Box(10, 10, 10)
    path = tmp_path / "preview.json"
    measurements = preview(path, {"box": box, "other": b.Pos(100, 0, 0) * box})
    result = make_mesh_section(
        path,
        measurements,
        SectionRequest(representation="mesh", offset=10, parts=["box"]),
        tmp_path / "slice",
        "a" * 32,
    )
    assert result["area_sum_mm2"] == pytest.approx(100)
    data = json.loads((tmp_path / "slice/section.json").read_text())
    assert np.min(np.array(data["regions"][0]["outer"])[:, 0]) == pytest.approx(15)
    tilted = make_mesh_section(
        path,
        measurements,
        SectionRequest(representation="mesh", offset=10, tilt=(30, 0), parts=["box"]),
        tmp_path / "tilt",
        "a" * 32,
    )
    assert tilted["area_sum_mm2"] == pytest.approx(100 / np.cos(np.pi / 6))
    empty = make_mesh_section(
        path,
        measurements,
        SectionRequest(representation="mesh", offset=999),
        tmp_path / "empty",
        "a" * 32,
    )
    assert empty["empty"]
    with pytest.raises(ValueError, match="Unknown output"):
        make_mesh_section(
            path,
            measurements,
            SectionRequest(representation="mesh", parts=["bad"]),
            tmp_path / "bad",
            "a" * 32,
        )
    wrong = copy.deepcopy(measurements)
    wrong["box"]["bounds"]["min"][0] += 10
    with pytest.raises(ValueError, match="world frame"):
        make_mesh_section(
            path, wrong, SectionRequest(representation="mesh"), tmp_path / "bad", "a" * 32
        )
    data = json.loads(path.read_text())
    data["parts"][0]["triangles"].pop()
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="closed"):
        make_mesh_section(
            path, measurements, SectionRequest(representation="mesh"), tmp_path / "bad", "a" * 32
        )


def test_mesh_worker_cache_and_default_remains_step(tmp_path):
    store, revision = seed(tmp_path)
    preview(store.directory(revision) / "preview.json", {"part": b.Box(10, 10, 10)})
    before = store.state()

    async def run():
        lock = asyncio.Semaphore(1)
        mesh = await generate(store, revision, SectionRequest(representation="mesh"), lock)
        cached = await generate(store, revision, SectionRequest(representation="mesh"), lock)
        exact = await generate(store, revision, SectionRequest(), lock)
        assert cached["cached"] and mesh["section_id"] == cached["section_id"]
        assert mesh["section_id"] != exact["section_id"]
        assert mesh["representation"] == "mesh" and exact["representation"] == "step"

    asyncio.run(run())
    assert store.state() == before
