from local_examples import load_local_example

import numpy as np
import pytest
import trimesh

from cad.schema import Document
from cad.gentle_twist import Surface, build_artifacts
from cad.solid_master import dimensions
from cad.casting_box import build


def document():
    doc = Document.model_validate(load_local_example("gentle-twist-pedestal-chamfer"))
    doc.solid_master.capture_shoulder = 2.0
    doc.solid_master.pedestal_base_chamfer = 0.0
    return doc


def inside(mesh, point):
    # Solid-angle winding of the actual exported triangles; no optional rtree dependency.
    a, b, c = np.moveaxis(mesh.triangles - np.asarray(point), 1, 0)
    la, lb, lc = [np.linalg.norm(v, axis=1) for v in (a, b, c)]

    def dot(u, v):
        return np.einsum("ij,ij->i", u, v)

    angle = 2 * np.arctan2(
        dot(a, np.cross(b, c)), la * lb * lc + dot(a, b) * lc + dot(b, c) * la + dot(c, a) * lb
    )
    return bool(abs(angle.sum()) > 2 * np.pi)


def test_shoulder_dimensions_and_flat_first_contact():
    doc = document()
    s = Surface.from_document(doc)[0]
    d = dimensions(doc, s)["captured_base"]
    assert d["flange_chamfer_top_radius"] == 86
    assert d["flange_chamfer_top_z"] == 1.5
    assert d["channel_roof_inner_z"] == pytest.approx(1.65)
    assert d["horizontal_roof_overhang"] == pytest.approx(2.06213203436)
    assert d["shoulder_vertical_clearance"] < d["vertical_capture_clearance"]
    t = build(doc, s)
    assert min(t.checks["captured_base"]["flat_shoulder_capture_interference_mm3"].values()) > 0
    assert max(t.checks["captured_base"]["sideways_wall_withdrawal_overlap_mm3"].values()) < 1e-6


def test_exported_stls_retain_floor(tmp_path):
    doc = document()
    doc.features[0].surface.angular_samples = 80
    doc.features[0].surface.vertical_intervals = 16
    s = Surface.from_document(doc)[0]
    t = build(doc, s)
    result = build_artifacts(doc, tmp_path)
    assert result["report"]["valid"]
    for report in result["report"]["export_validation"].values():
        assert report["open_edges"] == report["self_intersecting_faces"] == 0
    master = trimesh.load(tmp_path / "model.stl", force="mesh")
    master.apply_translation([0, 0, -1.5])
    for name, sign in [("wall_left", -1), ("wall_right", 1)]:
        wall = trimesh.load(tmp_path / f"{name}.stl", force="mesh")
        minimum = t.parts[name].bounding_box().min
        wall.apply_translation([minimum.X, minimum.Y, minimum.Z])
        seat = [sign * 85, 0, -1.6]
        roof = [sign * 85, 0, 1.675]
        gap = [sign * 85, 0, 1.575]
        assert inside(wall, seat) and not inside(master, seat)
        assert inside(master, np.array(seat) + [0, 0, 0.25])
        assert inside(wall, roof) and not inside(master, roof)
        # The flat shoulder blocks lift BEFORE the old ramp would touch at 0.212 mm.
        assert inside(master, np.array(roof) - [0, 0, 0.18])
        assert not inside(wall, gap) and not inside(master, gap)
