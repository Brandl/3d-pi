import math
from pathlib import Path

import pytest

from cad.schema import Document
from cad.gentle_twist import Surface, validate_mesh, build_artifacts
from cad.solid_master import dimensions, sample
from cad.casting_box import build


def document():
    doc = Document.model_validate_json(
        Path("examples/gentle-twist-thin-captured-base.json").read_text(encoding="utf-8")
    )
    doc.casting_box.rail_bottom_chamfer = 3.0
    doc.solid_master.plaster_corner_chamfer = 2.0
    return doc


def test_rail_ramps_clear_the_unsupported_underside():
    doc = document()
    surface = Surface.from_document(doc)[0]
    t = build(doc, surface)
    for name, x in (("wall_left", -4), ("wall_right", 4)):
        wall = t.parts[name]
        for y in (-95, 95):
            assert not wall.is_inside((x, y, 1.95))
            assert wall.is_inside((x, y, 2.05))
    assert t.checks["rail_bottom_ramp_degrees"] == 45
    assert t.checks["maximum_sampled_slide_overlap_mm3"] < 1e-6
    assert max(t.checks["integral_base_overlap_mm3"].values()) < 1e-6
    assert max(t.checks["captured_base"]["sideways_wall_withdrawal_overlap_mm3"].values()) < 1e-6
    assert t.checks["normal_dovetail_clearance_mm"] == 0.15


def test_corner_former_is_integral_and_preserves_clearance():
    doc = document()
    s = Surface.from_document(doc)[0]
    p = dimensions(doc, s)
    vertices, faces, *_ = sample(s, p, 360, 128)
    mesh, validation = validate_mesh(vertices, faces, expected_euler=2)
    assert validation["connected_components"] == 1
    assert len(faces) == 99360
    assert p["captured_base"]["chamfer_former_peak_z"] == 6.5
    assert p["captured_base"]["radial_clearance"] == 0.15
    assert p["captured_base"]["normal_capture_clearance"] == 0.15
    original = {**p, "plaster_corner_chamfer": 0}
    v0, f0, *_ = sample(s, original, 360, 128)
    import trimesh

    old = trimesh.Trimesh(v0, f0, process=False)
    # Revolved triangular cross-section (Pappus), compared with sampled mesh.
    expected = math.pi * 2**2 * (p["lip_outer_radius"] - 2 / 3)
    assert mesh.volume - old.volume == pytest.approx(expected, rel=0.0001)


def test_chamfer_exports(tmp_path):
    doc = document()
    doc.features[0].surface.angular_samples = 80
    doc.features[0].surface.vertical_intervals = 16
    result = build_artifacts(doc, tmp_path)
    assert result["report"]["valid"]
    assert result["report"]["casting_box"]["assembly_checks"]["rail_bottom_chamfer_mm"] == 3
    assert (
        result["report"]["casting_box"]["captured_base"]["dimensions"]["plaster_corner_chamfer"]
        == 2
    )


def test_too_small_rail_bevel_rejected():
    doc = document()
    doc.casting_box.rail_bottom_chamfer = 1.0
    with pytest.raises(ValueError, match="supporting collar"):
        build(doc, Surface.from_document(doc)[0])
