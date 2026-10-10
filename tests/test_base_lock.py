from local_examples import load_local_example
import math
import zipfile

import pytest
import trimesh

from cad.schema import Document
from cad.gentle_twist import Surface, build_artifacts, validate_mesh
from cad.solid_master import dimensions, sample
from cad.casting_box import build


def document():
    doc = Document.model_validate(load_local_example("gentle-twist-wide-end-down-master"))
    doc.base_lock = True
    doc.parameters["master_base_thickness"] = 6.0
    doc.parameters["master_base_overhang"] = 14.0
    return doc


def test_base_groove_is_part_of_one_master():
    doc = document()
    s = Surface.from_document(doc)[0]
    p = dimensions(doc, s)
    v, f, *_ = sample(s, p, 360, 128)
    mesh, report = validate_mesh(v, f, expected_euler=2)
    assert report["connected_components"] == 1
    assert mesh.bounds[0, 2] == -6
    assert mesh.extents[0] == 204
    ungrooved = {k: v for k, v in p.items() if k != "base_lock"}
    uv, uf, *_ = sample(s, ungrooved, 360, 128)
    original = trimesh.Trimesh(uv, uf, process=False)
    expected = math.pi * (87.4**2 - 84.6**2) * 1.5
    assert original.volume - mesh.volume == pytest.approx(expected, rel=0.0001)


def test_base_clamps_capture_and_withdraw():
    doc = document()
    t = build(doc, Surface.from_document(doc)[0])
    checks = t.checks["base_lock"]
    assert len(t.parts) == 8 and len(t.references) == 5
    assert min(checks["base_capture_interference_mm3"].values()) > 90
    assert min(checks["screw_blocks_wall_lift_mm3"].values()) > 9
    assert max(checks["clamp_removal_overlap_mm3"].values()) < 1e-6
    assert max(checks["purchased_hardware_interference_mm3"].values()) < 1e-6
    assert checks["gasket_interference_mm3"] < 1e-6
    d = checks["dimensions"]
    assert d["nominal_gasket_squeeze_percent"] == 25
    assert d["groove_fill_percent"] < 80
    assert min(d["inner_sealing_land"], d["outer_sealing_land"]) >= 0.59
    for name, part in t.parts.items():
        assert part.is_valid and len(part.solids()) == 1
        if name.startswith("base_clamp_"):
            assert t.print_parts[name].bounding_box().size.Z == pytest.approx(16, abs=1e-5)


def test_exports_exclude_printed_substitutes_for_purchased_items(tmp_path):
    doc = document()
    doc.features[0].surface.angular_samples = 80
    doc.features[0].surface.vertical_intervals = 16
    result = build_artifacts(doc, tmp_path)
    assert result["report"]["valid"]
    assert len(result["report"]["parts"]) == 14
    assert result["report"]["casting_box"]["base_lock"]["dimensions"]["oring_nominal_id"] == 170
    with zipfile.ZipFile(tmp_path / "casting-box.zip") as z:
        assert {"model.stl", "base_clamp_ne.stl", "base_clamp_sw.3mf", "wall_left.step"} <= set(
            z.namelist()
        )
        assert not any(name.startswith(("m5_", "base_gasket.")) for name in z.namelist())
        assert b"water-test" in z.read("READ-ME.txt")
    for name in ("ne", "nw", "se", "sw"):
        mesh = trimesh.load(tmp_path / f"base_clamp_{name}.stl", force="mesh")
        assert mesh.is_watertight and mesh.euler_number == 0
    assert (tmp_path / "render-exploded.png").stat().st_size > 1000


def test_inadequate_base_rejected():
    doc = document()
    doc.parameters["master_base_thickness"] = 4.0
    with pytest.raises(ValueError, match="Base clamps require"):
        dimensions(doc, Surface.from_document(doc)[0])
