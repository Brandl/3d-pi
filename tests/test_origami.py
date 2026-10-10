from local_examples import load_local_example

import numpy as np
import pytest

from cad.gentle_twist import Surface, validate_mesh
from cad.schema import Document
from cad.solid_master import dimensions, sample, tip_surface


def document():
    doc = Document.model_validate(load_local_example("gentle-twist-positive-lock-floor"))
    doc.features[0].surface.profile = "origami"
    doc.parameters.update(
        flute_count=20.0, twist_degrees=0.0, bottom_radius=16.0, bottom_amplitude=16.0 * 4 / 60
    )
    return doc


def test_twenty_sharp_folds_and_forty_planar_panels():
    doc = document()
    s = Surface.from_document(doc)[0]
    theta = np.arange(40) * np.pi / 20
    vertices = s.exterior(theta, s.height)[0]
    assert np.allclose(np.linalg.norm(vertices[::2, :2], axis=1), 64)
    assert np.allclose(np.linalg.norm(vertices[1::2, :2], axis=1), 56)
    for j in range(40):
        lo, hi = j * np.pi / 20, (j + 1) * np.pi / 20
        corners = np.array([s.exterior(lo, 0)[0], s.exterior(hi, 0)[0], s.exterior(lo, 78)[0]])
        normal = np.cross(corners[1] - corners[0], corners[2] - corners[0])
        normal /= np.linalg.norm(normal)
        angle, z = np.meshgrid(np.linspace(lo, hi, 9), np.linspace(0, 78, 9))
        points = s.exterior(angle, z)[0]
        assert np.max(np.abs((points - corners[0]) @ normal)) < 1e-10
        normals = s.exterior(np.linspace(lo + 0.001, hi - 0.001, 7), 39)[1]
        assert np.max(np.abs(normals - normals[0])) < 1e-10


def test_base_unchanged_closed_mesh_and_circular_neck():
    doc = document()
    s = Surface.from_document(doc)[0]
    p = dimensions(doc, s)
    v, f, *_ = sample(s, p, 360, 128)
    _, report = validate_mesh(v, f, expected_euler=2)
    assert report["connected_components"] == 1 and report["self_intersecting_faces"] == 0
    old = Document.model_validate(load_local_example("gentle-twist-positive-lock-floor"))
    old_s = Surface.from_document(old)[0]
    old_p = dimensions(old, old_s)
    ov, of, *_ = sample(old_s, old_p, 360, 128)
    assert p["captured_base"] == old_p["captured_base"]
    # Base material strictly below the body attachment plane is identical.
    triangles = v[f]
    before = ov[of]
    assert np.array_equal(
        triangles[np.min(triangles[:, :, 2], axis=1) < 20 - 1e-8],
        before[np.min(before[:, :, 2], axis=1) < 20 - 1e-8],
    )
    theta = np.linspace(0, 2 * np.pi, 401)
    rings = np.array([tip_surface(s, p, theta, h)[0] for h in np.linspace(0, 5, 81)])
    radius = np.linalg.norm(rings[:, :, :2], axis=2)
    assert np.max(np.diff(radius, axis=0)) < 1e-10
    assert np.allclose(radius[-1], 14)
    start, n = s.exterior(-theta, 0)
    start[:, 1] *= -1
    start[:, 2] = 98
    n[:, 1:] *= -1
    t, tn = tip_surface(s, p, theta, 0)
    assert np.allclose(start, t)
    # At sharp fold vertices two face normals exist; compare away from creases.
    angles = theta + 0.0001
    _, n = s.exterior(-angles, 0)
    n[:, 1:] *= -1
    assert np.allclose(n, tip_surface(s, p, angles, 0)[1])
    assert p["axial_draw_no_undercut"] and p["tip_blend_no_undercut"]


def test_origami_rejects_twist_and_nonplanar_scaling():
    doc = document()
    doc.parameters["twist_degrees"] = 10.0
    with pytest.raises(ValueError, match="planar"):
        Surface.from_document(doc)
    doc = document()
    doc.parameters["bottom_amplitude"] = 0.3
    with pytest.raises(ValueError, match="planar"):
        Surface.from_document(doc)
