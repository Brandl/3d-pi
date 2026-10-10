import json
import math
from local_examples import load_local_example
from cad.demo import enclosure_document

import build123d as b
import ezdxf
import pytest
import trimesh

from cad.geometry import build_artifacts, construct, inspection
from cad.schema import Document
from test_schema import box_document


@pytest.fixture(scope="module")
def enclosure():
    return Document.model_validate(enclosure_document())


def test_enclosure_changes(enclosure):
    first, expressions = construct(enclosure)
    original = inspection(first, enclosure, expressions)
    changed = enclosure.model_copy(deep=True)
    changed.parameters.update({"wall": 3, "width": 100, "hole_offset": 10})
    parts, expressions = construct(changed)
    report = inspection(parts, changed, expressions)
    assert report["valid"]
    assert report["parts"]["enclosure"]["x"] == pytest.approx(100)
    assert report["parts"]["enclosure"]["volume"] > original["parts"]["enclosure"]["volume"]
    # Check actual hole geometry, not merely the parameter label.
    for x in (10, 90):
        for y in (10, 40):
            assert not parts["enclosure"].is_inside((x, y, 1))
            assert parts["enclosure"].is_inside((x + 2, y, 1))


def test_all_exports_and_renders(enclosure, tmp_path):
    result = build_artifacts(enclosure, tmp_path)
    assert result["report"]["valid"]
    step = b.import_step(tmp_path / "model.step")
    assert len(step.solids()) == 2
    p = enclosure.parameters
    span = 2 * p["width"] + p["gap"]
    assert step.bounding_box().size.X == pytest.approx(span)
    # Independent mesh reader validates the printing artifacts.
    stl = trimesh.load(tmp_path / "model.stl", force="mesh")
    assert stl.is_watertight
    expected_volume = (
        p["width"] * p["depth"] * (p["height"] + p["lid_thickness"])
        - (p["width"] - 2 * p["wall"]) * (p["depth"] - 2 * p["wall"]) * (p["height"] - p["wall"])
        - 4 * math.pi * p["hole_radius"] ** 2 * (p["wall"] + p["lid_thickness"])
    )
    assert stl.volume == pytest.approx(expected_volume, rel=0.003)
    scene = trimesh.load(tmp_path / "model.3mf", force="scene")
    assert len(scene.geometry) == 2
    assert all(mesh.is_watertight for mesh in scene.geometry.values())
    assert scene.bounds[1][0] == pytest.approx(span)
    dxf = ezdxf.readfile(tmp_path / "section-lid_profile.dxf")
    assert dxf.units == 4  # millimeters
    assert not dxf.audit().has_errors
    assert len(dxf.modelspace().query("CIRCLE")) == 4
    for view in ("iso", "top", "front"):
        assert (tmp_path / f"render-{view}.png").read_bytes().startswith(b"\x89PNG")
        review = (tmp_path / f"review-{view}.png").read_bytes()
        assert review.startswith(b"\x89PNG")
        assert review != (tmp_path / f"render-{view}.png").read_bytes()
    preview = json.loads((tmp_path / "preview.json").read_text(encoding="utf-8"))
    assert len(preview["parts"]) == 2
    assert all(p["edges"] and p["triangles"] for p in preview["parts"])


def test_fillets_transforms_and_polygon():
    doc = Document.model_validate(
        {
            "features": [
                {
                    "name": "polygon",
                    "op": "extrude",
                    "points": [[0, 0], [20, 0], [20, 10], [0, 10]],
                    "height": 5,
                },
                {
                    "name": "rounded",
                    "op": "fillet",
                    "inputs": ["polygon"],
                    "radius": 1,
                    "edges": "parallel_z",
                },
                {"name": "moved", "op": "transform", "inputs": ["rounded"], "position": [10, 0, 0]},
            ],
            "outputs": [{"name": "part", "feature": "moved"}],
        }
    )
    parts, _ = construct(doc)
    assert parts["part"].is_valid
    assert parts["part"].bounding_box().min.X == pytest.approx(10)
    assert parts["part"].volume < 1000


def test_invalid_dimension_names_feature():
    doc = box_document()
    doc["parameters"]["width"] = -10
    with pytest.raises(ValueError, match="Feature 'block'"):
        construct(Document.model_validate(doc))


@pytest.mark.parametrize("filename", ["bracket.json", "mounting-plate.json"])
def test_example_regeneration(filename):
    doc = Document.model_validate(load_local_example(filename))
    for width in (60, 100):
        doc.parameters["width"] = width
        parts, expressions = construct(doc)
        assert inspection(parts, doc, expressions)["valid"]


def test_failed_assertion():
    doc = box_document()
    doc["checks"][0]["expected"] = 999
    parsed = Document.model_validate(doc)
    parts, expressions = construct(parsed)
    assert not inspection(parts, parsed, expressions)["valid"]
