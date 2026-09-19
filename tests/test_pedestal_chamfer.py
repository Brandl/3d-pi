import math
from pathlib import Path

import numpy as np
import pytest
import trimesh

from cad.schema import Document
from cad.gentle_twist import Surface, validate_mesh, build_artifacts
from cad.solid_master import dimensions, sample
from cad.casting_box import build


def document():
    doc = Document.model_validate_json(
        Path("examples/gentle-twist-cutting-neck.json").read_text(encoding="utf-8")
    )
    doc.solid_master.pedestal_base_chamfer = 2.0
    return doc


def test_full_circumference_pedestal_chamfer():
    doc = document()
    surface = Surface.from_document(doc)[0]
    p = dimensions(doc, surface)
    vertices, faces, *_ = sample(surface, p, 360, 128)
    mesh, report = validate_mesh(vertices, faces, expected_euler=2)
    assert report["connected_components"] == 1
    assert report["self_intersecting_faces"] == 0
    radius = np.linalg.norm(vertices[:, :2], axis=1)
    assert np.count_nonzero(np.isclose(radius, 70) & np.isclose(vertices[:, 2], 0)) == 360
    assert np.count_nonzero(np.isclose(radius, 68) & np.isclose(vertices[:, 2], 2)) == 360
    v0, f0, *_ = sample(surface, {**p, "pedestal_base_chamfer": 0}, 360, 128)
    original = trimesh.Trimesh(v0, f0, process=False)
    # Revolved triangular addition: area c^2/2, centroid at R+c/3.
    expected = math.pi * 2**2 * (68 + 2 / 3)
    assert mesh.volume - original.volume == pytest.approx(expected, rel=0.0001)
    assert np.array_equal(mesh.bounds, original.bounds)


def test_fit_and_exports(tmp_path):
    doc = document()
    surface = Surface.from_document(doc)[0]
    tooling = build(doc, surface)
    assert max(tooling.checks["integral_base_overlap_mm3"].values()) < 1e-6
    assert tooling.checks["normal_dovetail_clearance_mm"] == 0.15
    assert (
        max(tooling.checks["captured_base"]["sideways_wall_withdrawal_overlap_mm3"].values()) < 1e-6
    )
    doc.features[0].surface.angular_samples = 80
    doc.features[0].surface.vertical_intervals = 16
    result = build_artifacts(doc, tmp_path)
    assert result["report"]["valid"]
    assert result["report"]["analytic_surface"]["dimensions"]["pedestal_base_chamfer"] == 2
    for report in result["report"]["export_validation"].values():
        assert report["connected_components"] == 1
        assert report["open_edges"] == report["self_intersecting_faces"] == 0


def test_chamfer_requires_pedestal_orientation():
    doc = document()
    doc.solid_master.wide_end_down = False
    with pytest.raises(ValueError):
        dimensions(doc, Surface.from_document(doc)[0])
