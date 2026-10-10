import json
import zipfile
from local_examples import load_local_example

import build123d as b
import numpy as np
import pytest
import trimesh

from cad.casting_box import artifacts, box, build, overlap
from cad.gentle_twist import Surface
from cad.schema import Document


@pytest.fixture(scope="module")
def document():
    return Document.model_validate(load_local_example("gentle-twist-casting-box"))


@pytest.fixture(scope="module")
def tooling(document):
    return build(document, Surface.from_document(document)[0])


def test_three_sided_halves_and_open_cavity(tooling):
    assert len(tooling.parts) == 4
    assert tooling.dimensions["inner_width"] == 168
    assert tooling.dimensions["wall_height"] == 98
    for name, sign in (("wall_left", -1), ("wall_right", 1)):
        part = tooling.parts[name]
        assert part.is_valid and len(part.solids()) == 1
        assert part.is_inside((sign * 86, 0, 50))
        assert part.is_inside((sign * 40, 86, 50))
        assert part.is_inside((sign * 40, -86, 50))
        assert not part.is_inside((sign * 40, 0, 0.1))
        assert not part.is_inside((sign * 40, 0, 97.9))
    assert tooling.checks["plaster_cavity_intrusion_mm3"] < 1e-6
    assert tooling.checks["open_top"] and tooling.checks["open_bottom"]


def test_lock_clearance_slide_and_retention(tooling):
    assert max(tooling.checks["assembled_pair_overlap_mm3"].values()) < 1e-6
    assert tooling.checks["maximum_sampled_slide_overlap_mm3"] < 1e-6
    assert min(tooling.checks["spread_2mm_retention_interference_mm3"].values()) > 100
    assert tooling.checks["normal_dovetail_clearance_mm"] == 0.3
    assert tooling.parts["lock_back"].bounding_box().max.Z == 93
    # The stop cap blocks travel below the intended seated pose.
    lowered = b.Pos(0, 0, -1) * tooling.parts["lock_back"]
    assert overlap(lowered, tooling.parts["wall_left"]) > 0


def test_overlap_handles_compounds():
    first = b.Compound(children=[box(0, 0, 0, 10, 10, 10)])
    second = box(5, 0, 0, 10, 10, 10)
    assert overlap(first, second) == pytest.approx(500)


def test_print_orientation(tooling):
    for name, part in tooling.print_parts.items():
        np.testing.assert_allclose(list(part.bounding_box().min), [0, 0, 0], atol=1e-6)
        expected = [88, 192, 98] if name.startswith("wall") else [23.121110255, 83, 11]
        np.testing.assert_allclose(list(part.bounding_box().size), expected, atol=1e-6)
        assert part.volume == pytest.approx(tooling.parts[name].volume)


@pytest.mark.parametrize("profile", ["rectangular", "round"])
def test_tooling_exports(document, tmp_path, profile):
    document = document.model_copy(deep=True)
    document.casting_box.profile = profile
    result = artifacts(document, Surface.from_document(document)[0], tmp_path)
    assert len(result["parts"]) == 4
    for name in result["parts"]:
        mesh = trimesh.load(tmp_path / f"{name}.stl", force="mesh")
        assert mesh.is_watertight and mesh.is_winding_consistent
        assert mesh.euler_number == 2
        assert mesh.volume > 0
        for fmt in ("stl", "3mf"):
            assert result["report"]["part_validation"][name][fmt]["self_intersecting_faces"] == 0
        step = b.import_step(tmp_path / f"{name}.step")
        assert len(step.solids()) == 1
    assert len(b.import_step(tmp_path / "casting-box.step").solids()) == 4
    with zipfile.ZipFile(tmp_path / "casting-box.zip") as archive:
        assert len([n for n in archive.namelist() if n.endswith(".stl")]) == 4
        assert "model.stl" not in archive.namelist()  # Reference dripper is not tooling.
        source = json.loads(archive.read("parametric-source.json"))
        assert source["parameters"]["twist_degrees"] == 40
        assert source["parameters"]["top_amplitude"] == 4


def test_round_halves_are_cylindrical_and_keep_the_locks(document, tooling):
    changed = document.model_copy(deep=True)
    changed.casting_box.profile = "round"
    round_form = build(changed, Surface.from_document(changed)[0])
    assert round_form.dimensions["inner_diameter"] == 168
    assert round_form.dimensions["outer_diameter"] == 176
    for name, angles in (("wall_right", [-60, 0, 60]), ("wall_left", [120, 180, 240])):
        shape = round_form.parts[name]
        assert any(face.geom_type == b.GeomType.CYLINDER for face in shape.faces())
        assert shape.volume < tooling.parts[name].volume
        for angle in np.deg2rad(angles):
            assert shape.is_inside((86 * np.cos(angle), 86 * np.sin(angle), 50))
            assert not shape.is_inside((83 * np.cos(angle), 83 * np.sin(angle), 50))
            assert not shape.is_inside((89 * np.cos(angle), 89 * np.sin(angle), 50))
    assert not round_form.parts["wall_right"].is_inside((85, 85, 50))
    assert round_form.checks["plaster_cavity_intrusion_mm3"] < 1e-6
    assert round_form.checks["maximum_sampled_slide_overlap_mm3"] < 1e-6
    assert min(round_form.checks["spread_2mm_retention_interference_mm3"].values()) > 100
    for name in ("lock_front", "lock_back"):
        assert round_form.parts[name].volume == pytest.approx(tooling.parts[name].volume)


def test_invalid_lock_length_rejected(document):
    changed = document.model_copy(deep=True)
    changed.parameters["lock_length"] = 120
    with pytest.raises(ValueError, match="Lock length"):
        build(changed, Surface.from_document(changed)[0])
