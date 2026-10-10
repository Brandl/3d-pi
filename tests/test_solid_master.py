import math
from local_examples import load_local_example

import numpy as np
import pytest

from cad.casting_box import build
from cad.gentle_twist import Surface, validate_mesh
from cad.schema import Document, SolidMaster
from cad.solid_master import dimensions, sample


def document():
    doc = Document.model_validate(load_local_example("gentle-twist-round-casting-box"))
    doc.solid_master = SolidMaster()
    return doc


def test_master_is_one_filled_continuous_solid():
    doc = document()
    surface = Surface.from_document(doc)[0]
    p = dimensions(doc, surface)
    vertices, faces, normals, flat, edges = sample(surface, p, 360, 128)
    mesh, report = validate_mesh(vertices, faces, expected_euler=2)
    assert report["connected_components"] == 1
    assert report["open_edges"] == report["self_intersecting_faces"] == 0
    assert np.allclose(mesh.bounds, [[-92, -92, -4], [92, 92, 98]])
    cone = math.pi * 78 * ((15**2 + 15 * 60 + 60**2) / 3 + (0.3**2 + 0.3 * 4 + 4**2) / 6)
    expected = cone + math.pi * (68**2 * 20 + 92**2 * 4 + (83.7**2 - 80.7**2) * 4)
    assert mesh.volume == pytest.approx(expected, rel=0.0003)
    original, _ = surface.exterior(np.arange(360) * 2 * math.pi / 360, 78)
    assert np.allclose(vertices[(6 + 128) * 360 : (7 + 128) * 360], original)
    assert np.allclose(np.linalg.norm(normals, axis=1), 1)
    for span in flat:
        actual = mesh.face_normals[span["start"] : span["start"] + span["count"]]
        assert np.allclose(actual, span["normal"])


def test_wide_end_down_is_rigidly_rotated_and_draws_upward():
    doc = document()
    doc.solid_master.wide_end_down = True
    surface = Surface.from_document(doc)[0]
    p = dimensions(doc, surface)
    assert p["axial_draw_no_undercut"]
    assert p["minimum_flute_radial_taper"] > 0.2
    angular, vertical = 120, 32
    vertices, faces, normals, flat, _ = sample(surface, p, angular, vertical)
    mesh, report = validate_mesh(vertices, faces, expected_euler=2)
    assert report["connected_components"] == 1
    assert np.allclose(mesh.bounds, [[-92, -92, -4], [92, 92, 98]])
    theta = np.arange(angular) * 2 * np.pi / angular
    for k in (0, vertical // 2, vertical):
        original, normal = surface.exterior(-theta, surface.height * (1 - k / vertical))
        original[:, 1] *= -1
        original[:, 2] = 98 - original[:, 2]
        normal[:, 1:] *= -1
        start = (8 + k) * angular
        assert np.allclose(vertices[start : start + angular], original)
        assert np.allclose(normals[start : start + angular], normal)
    body = vertices[8 * angular : -2].reshape(vertical + 1, angular, 3)
    radii = np.linalg.norm(body[:, :, :2], axis=2)
    assert np.all(np.diff(radii, axis=0) < 0)
    assert np.allclose(body[0, :, 2], 20)
    assert np.allclose(body[-1, :, 2], 98)
    for span in flat:
        assert np.allclose(
            mesh.face_normals[span["start"] : span["start"] + span["count"]], span["normal"]
        )
    other_vertices, other_faces, *_ = sample(
        surface, {**p, "wide_end_down": False}, angular, vertical
    )
    import trimesh

    assert mesh.volume == pytest.approx(
        trimesh.Trimesh(other_vertices, other_faces, process=False).volume
    )


@pytest.mark.parametrize("wide_end_down", [False, True])
def test_master_exports_and_bundle(tmp_path, wide_end_down):
    import json
    import zipfile
    import trimesh
    from cad.gentle_twist import build_artifacts

    doc = document()
    doc.solid_master.wide_end_down = wide_end_down
    doc.features[0].surface.angular_samples = 80
    doc.features[0].surface.vertical_intervals = 16
    for check in doc.checks:
        if check.metric == "z":
            check.expected = "height+24"
    result = build_artifacts(doc, tmp_path)
    assert result["report"]["valid"]
    for validation in result["report"]["export_validation"].values():
        assert validation["connected_components"] == 1
        assert validation["euler_characteristic"] == 2
    printed = trimesh.load(tmp_path / "model.stl", force="mesh")
    assert printed.bounds[0, 2] == pytest.approx(0)
    assert printed.bounds[1, 2] == pytest.approx(102)
    with zipfile.ZipFile(tmp_path / "casting-box.zip") as archive:
        assert {"model.stl", "model.3mf", "wall_left.step", "lock_back.stl"} <= set(
            archive.namelist()
        )
        source = json.loads(archive.read("parametric-source.json"))
        assert source["solid_master"]


def test_base_seats_without_interference():
    doc = document()
    result = build(doc, Surface.from_document(doc)[0])
    assert max(result.checks["integral_base_overlap_mm3"].values()) < 1e-6
    assert max(result.checks["base_lip_sampled_wall_withdrawal_overlap_mm3"].values()) < 1e-6
    assert result.checks["base_lip_radial_clearance_mm"] == 0.3
    assert result.checks["master_collar_to_wall_clearance_mm"] == 16


@pytest.mark.parametrize(
    "change",
    [{"collar_radius": 60}, {"collar_radius": 84}, {"lip_clearance": 0}, {"collar_height": 10}],
)
def test_bad_master_dimensions_rejected(change):
    doc = document()
    doc.solid_master = SolidMaster(**change)
    with pytest.raises(ValueError):
        dimensions(doc, Surface.from_document(doc)[0])
