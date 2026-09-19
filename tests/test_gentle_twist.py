from pathlib import Path

import numpy as np
import pytest

from cad.gentle_twist import Surface, analytic_checks, sample_mesh, validate_mesh
from cad.schema import Document


@pytest.fixture(scope="module")
def specification():
    doc = Document.model_validate_json(
        Path("examples/gentle-twist.json").read_text(encoding="utf-8")
    )
    return doc, Surface.from_document(doc)[0]


@pytest.fixture(scope="module")
def geometry(specification):
    _, surface = specification
    return sample_mesh(surface, 360, 128)


def test_exterior_reference_profiles_and_twist(specification):
    _, surface = specification
    for z, mean, amplitude, degrees in [
        (0, 15, 0.15, 0),
        (19.5, 26.25, 0.6125, 5),
        (39, 37.5, 1.075, 10),
        (58.5, 48.75, 1.5375, 15),
        (78, 60, 2, 20),
    ]:
        theta = np.arange(360) * 2 * np.pi / 360 + np.deg2rad(degrees)
        points, _ = surface.exterior(theta, z)
        radii = np.linalg.norm(points[:, :2], axis=1)
        assert radii.mean() == pytest.approx(mean, abs=1e-12)
        assert radii[0] == pytest.approx(mean + amplitude)
        assert radii[18] == pytest.approx(mean - amplitude)
        np.testing.assert_allclose(radii[::36], mean + amplitude, atol=1e-12)
        assert np.arctan2(points[0, 1], points[0, 0]) == pytest.approx(np.deg2rad(degrees))


def test_analytic_normals_match_derivatives(specification):
    _, surface = specification
    theta = np.linspace(-0.1, 2 * np.pi + 0.1, 313)
    u = np.linspace(-5, 83, 313)
    step = 1e-5
    tangent_theta = (
        surface.exterior(theta + step, u)[0] - surface.exterior(theta - step, u)[0]
    ) / (2 * step)
    tangent_u = (surface.exterior(theta, u + step)[0] - surface.exterior(theta, u - step)[0]) / (
        2 * step
    )
    normal = np.cross(tangent_theta, tangent_u)
    normal /= np.linalg.norm(normal, axis=1, keepdims=True)
    np.testing.assert_allclose(normal, surface.exterior(theta, u)[1], atol=2e-9)
    np.testing.assert_allclose(
        surface.exterior(0, u)[0], surface.exterior(2 * np.pi, u)[0], atol=1e-12
    )
    np.testing.assert_allclose(
        surface.exterior(0, u)[1], surface.exterior(2 * np.pi, u)[1], atol=1e-12
    )


def test_mesh_topology_and_unobstructed_outlet(geometry):
    vertices, faces, _, _ = geometry
    assert vertices.shape == (92880, 3)
    assert faces.shape == (185760, 3)
    mesh, result = validate_mesh(vertices, faces)
    assert (
        result["open_edges"]
        == result["non_manifold_edges"]
        == result["self_intersecting_faces"]
        == 0
    )
    assert result["degenerate_triangles"] == 0
    assert result["euler_characteristic"] == 0  # A single closed wall boundary with a through bore.
    assert result["connected_components"] == 1
    assert result["consistent_winding"] and result["positive_signed_volume"]
    assert np.min(np.linalg.norm(vertices[:, :2], axis=1)) > 11.4
    # End faces are annuli, never triangle fans or disks across the cavity.
    rims = faces[4 * 360 * 128 :]
    assert np.all(vertices[rims[:720], 2] == 0)
    assert np.all(vertices[rims[720:], 2] == 78)
    np.testing.assert_allclose(mesh.face_normals[-1440:-720, 2], -1, atol=1e-12)
    np.testing.assert_allclose(mesh.face_normals[-720:, 2], 1, atol=1e-12)
    assert len(np.unique(vertices, axis=0)) == len(vertices)


def test_normal_offset_and_trimmed_opening_dimensions(specification, geometry):
    _, surface = specification
    vertices, faces, _, u = geometry
    report = analytic_checks(surface, vertices, faces, u, 360, 128)
    assert report["maximum_normal_thickness_error_mm"] < 1e-9
    assert report["maximum_offset_vector_error_mm"] < 1e-9
    assert report["symmetry_error_mm"] < 1e-9
    assert report["bottom_internal_diameters_mm"]["minimum"] == pytest.approx(22.843, abs=0.0005)
    assert report["bottom_internal_diameters_mm"]["maximum"] == pytest.approx(23.301, abs=0.0005)
    assert report["top_internal_diameters_mm"]["minimum"] == pytest.approx(109.143, abs=0.0005)
    assert report["top_internal_diameters_mm"]["maximum"] == pytest.approx(117.001, abs=0.0005)
    assert report["mean_cone_included_angle_degrees"] == pytest.approx(59.9633, abs=0.00005)
    assert report["sampled_triangle_centroid_error_mm"]["exterior"] < 0.011
    assert report["sampled_triangle_centroid_error_mm"]["interior"] < 0.009
    # Interior points on the lower finished plane originate BELOW that plane.
    assert np.all(u[0] < 0)
    assert np.all(u[-1] < 78)
    theta = np.arange(360) * 2 * np.pi / 360
    inner, _, _ = surface.inner_ring(theta, 78)
    delta = np.angle(np.exp(1j * (np.arctan2(inner[:, 1], inner[:, 0]) - theta)))
    assert 0.001 < np.max(np.abs(delta)) < 0.1


def test_self_intersection_detector_positive_control():
    vertices = np.array(
        [[-1.0, -1, 0], [1, -1, 0], [0, 1, 0], [0, -0.5, -1], [0, -0.5, 1], [0, 0.5, 0]]
    )
    with pytest.raises(ValueError, match="'self_intersecting_faces': 2"):
        validate_mesh(vertices, np.array([[0, 1, 2], [3, 4, 5]]))


def test_parameter_edits_regenerate_and_invalid_sampling_is_rejected(specification):
    doc, original = specification
    changed = doc.model_copy(deep=True)
    changed.parameters["twist_degrees"] = 10
    new, _ = Surface.from_document(changed)
    assert new.twist == pytest.approx(original.twist / 2)
    changed.features[0].surface.angular_samples = 121
    with pytest.raises(ValueError, match="divisible"):
        Surface.from_document(changed)
