from local_examples import load_local_example
import zipfile

import pytest

from cad.schema import Document
from cad.gentle_twist import Surface, validate_mesh, build_artifacts
from cad.solid_master import dimensions, sample
from cad.casting_box import build


def document():
    doc = Document.model_validate(load_local_example("gentle-twist-locked-base"))
    doc.base_lock = False
    doc.captured_base = True
    doc.parameters["master_base_overhang"] = 0.0
    return doc


def test_captured_floor_load_and_removal():
    doc = document()
    t = build(doc, Surface.from_document(doc)[0])
    assert set(t.parts) == {"wall_left", "wall_right", "lock_front", "lock_back"}
    assert not t.references
    c = t.checks["captured_base"]
    assert c["dimensions"]["seat_width"] == 7
    assert c["dimensions"]["vertical_capture_clearance"] == 0.3
    assert min(c["downward_floor_support_interference_mm3"].values()) > 400
    assert min(c["upward_floor_capture_interference_mm3"].values()) > 300
    assert max(c["sideways_wall_withdrawal_overlap_mm3"].values()) < 1e-6
    assert max(t.checks["integral_base_overlap_mm3"].values()) < 1e-6
    assert not c["leak_tightness_verified"]
    for part in t.parts.values():
        assert part.is_valid and len(part.solids()) == 1
    assert t.parts["wall_left"].bounding_box().min.Z == pytest.approx(-10, abs=1e-6)
    assert t.parts["wall_left"].bounding_box().min.X == pytest.approx(-94, abs=1e-6)


def test_flanged_master_is_closed_without_zero_width_faces():
    doc = document()
    surface = Surface.from_document(doc)[0]
    vertices, faces, *_ = sample(surface, dimensions(doc, surface), 360, 128)
    mesh, validation = validate_mesh(vertices, faces, expected_euler=2)
    assert validation["connected_components"] == 1
    assert validation["degenerate_triangles"] == validation["self_intersecting_faces"] == 0
    assert len(faces) == 99360
    assert mesh.extents.tolist() == [176, 176, 104]


def test_all_printed_exports(tmp_path):
    doc = document()
    doc.features[0].surface.angular_samples = 80
    doc.features[0].surface.vertical_intervals = 16
    result = build_artifacts(doc, tmp_path)
    assert result["report"]["valid"]
    assert len(result["report"]["parts"]) == 5
    assert (
        result["report"]["casting_box"]["captured_base"]["dimensions"]["hardware_required"] is False
    )
    with zipfile.ZipFile(tmp_path / "casting-box.zip") as archive:
        names = archive.namelist()
        assert len([n for n in names if n.endswith(".stl")]) == 5
        assert "joint-section.svg" in names
        import xml.etree.ElementTree as ET

        assert ET.fromstring(archive.read("joint-section.svg")).tag.endswith("svg")
        assert not any(n.startswith(("base_clamp_", "base_gasket", "m5_")) for n in names)
        assert b"No gasket, screws, nuts or external clamps" in archive.read("READ-ME.txt")


def test_taller_walls_leave_plaster_cap_without_changing_master():
    import numpy as np

    doc = document()
    surface = Surface.from_document(doc)[0]
    before = sample(surface, dimensions(doc, surface), 80, 16)
    doc.parameters["mold_top_clearance"] = 40.0
    doc.parameters["lock_length"] = 100.0
    m = dimensions(doc, surface)
    assert m["plaster_cover_above_master"] == 20
    assert m["master_top_z"] == 98 and m["form_top_z"] == 118
    after = sample(surface, m, 80, 16)
    assert np.array_equal(before[0], after[0])
    assert np.array_equal(before[1], after[1])
    tooling = build(doc, surface)
    assert tooling.dimensions["wall_height"] == 118
    assert tooling.dimensions["rail_height"] == 110
    assert tooling.dimensions["lock_bottom_z"] == 10
    assert tooling.dimensions["lock_top_z"] == 113
    assert tooling.parts["wall_left"].bounding_box().size.Z == pytest.approx(128, abs=1e-6)


def test_thin_skins_reinforced_rim_and_015_normal_fits(tmp_path):
    import math
    from cad.captured_base import master_base

    doc = document()
    doc.parameters.update(
        mold_wall_thickness=1.5,
        master_base_thickness=1.5,
        master_lip_height=4.5,
        master_lip_clearance=0.15,
        lock_clearance=0.15,
    )
    doc.solid_master.capture_normal_clearance = 0.15
    s = Surface.from_document(doc)[0]
    m = dimensions(doc, s)
    d = m["captured_base"]
    assert d["flat_floor_thickness"] == d["curved_wall_thickness"] == 1.5
    assert d["normal_capture_clearance"] == d["radial_clearance"] == 0.15
    assert d["vertical_capture_clearance"] == pytest.approx(0.15 * math.sqrt(2))
    assert d["local_reinforcement_height"] == 6
    base = master_base(m, d)
    assert base.is_inside((75, 0, -0.75))
    assert not base.is_inside((75, 0, 0.1))
    assert not base.is_inside((75, 0, -1.6))
    t = build(doc, s)
    wall = t.parts["wall_right"]
    assert wall.is_inside((84.75, 0, 60))
    assert not wall.is_inside((85.6, 0, 60))
    assert not wall.is_inside((88.1, 0, -1))
    assert wall.is_inside((88.2, 0, -1))
    assert not wall.is_inside((86 + 0.1 / math.sqrt(2), 0, 1.5 + 0.1 / math.sqrt(2)))
    assert wall.is_inside((86 + 0.2 / math.sqrt(2), 0, 1.5 + 0.2 / math.sqrt(2)))
    assert t.checks["normal_dovetail_clearance_mm"] == 0.15
    assert max(t.checks["integral_base_overlap_mm3"].values()) < 1e-6
    assert max(t.checks["captured_base"]["sideways_wall_withdrawal_overlap_mm3"].values()) < 1e-6
    doc.features[0].surface.angular_samples = 80
    doc.features[0].surface.vertical_intervals = 16
    result = build_artifacts(doc, tmp_path)
    assert result["report"]["valid"]
    assert result["report"]["parts"]["gentle_twist"]["z"] == 99.5
    assert result["report"]["mesh_validation"]["connected_components"] == 1


def test_mutually_exclusive_joints():
    doc = document().model_dump()
    doc["base_lock"] = True
    with pytest.raises(ValueError, match="Captured dry base"):
        Document.model_validate(doc)
