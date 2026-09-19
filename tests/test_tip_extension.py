from pathlib import Path

import numpy as np
import pytest

from cad.schema import Document
from cad.gentle_twist import Surface, validate_mesh
from cad.solid_master import dimensions, sample, tip_surface


def document():
    doc = Document.model_validate_json(
        Path("examples/gentle-twist-chamfered-form.json").read_text(encoding="utf-8")
    )
    doc.solid_master.tip_extension = 5.0
    return doc


def test_tip_blend_is_tangent_circular_and_draw_safe():
    doc = document()
    s = Surface.from_document(doc)[0]
    p = dimensions(doc, s)
    theta = np.arange(360) * 2 * np.pi / 360
    start, normal = tip_surface(s, p, theta, 0)
    old, old_normal = s.exterior(-theta, 0)
    old[:, 1] *= -1
    old[:, 2] = 98 - old[:, 2]
    old_normal[:, 1:] *= -1
    assert np.allclose(start, old)
    assert np.allclose(normal, old_normal)
    previous = np.linalg.norm(start[:, :2], axis=1)
    for distance in np.linspace(0, 5, 101):
        points, normals = tip_surface(s, p, theta, distance)
        radius = np.linalg.norm(points[:, :2], axis=1)
        assert np.all(radius <= previous + 1e-10)
        assert np.allclose(np.linalg.norm(normals, axis=1), 1)
        previous = radius
    for distance in (3, 4, 5):
        points, normals = tip_surface(s, p, theta, distance)
        assert np.allclose(np.linalg.norm(points[:, :2], axis=1), 14)
        assert np.allclose(normals[:, 2], 0)
        assert np.allclose(points[:, 2], 98 + distance)
    assert p["plaster_cover_above_master"] == 15
    assert p["tip_blend_no_undercut"]


def test_extended_master_is_one_closed_solid():
    doc = document()
    s = Surface.from_document(doc)[0]
    p = dimensions(doc, s)
    v, f, *_ = sample(s, p, 360, 128)
    mesh, report = validate_mesh(v, f, expected_euler=2)
    assert report["connected_components"] == 1
    assert report["self_intersecting_faces"] == 0
    assert mesh.bounds[1, 2] == 103
    assert mesh.extents[2] == 104.5
    assert len(f) == 111600


def test_widening_tip_rejected():
    doc = document()
    doc.solid_master.tip_radius = 15.0
    with pytest.raises(ValueError, match="undercut"):
        dimensions(doc, Surface.from_document(doc)[0])
