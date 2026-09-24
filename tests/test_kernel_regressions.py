"""Regression cases from the trilock workflow; no production data required."""

import pytest

from cad.geometry import construct, inspection
from cad.schema import Document


def document(features, output="result"):
    return Document.model_validate(
        {"features": features, "outputs": [{"name": "part", "feature": output}]}
    )


def test_multi_operand_intersection_normalizes_disconnected_intermediate():
    features = [
        {"name": "a", "op": "box", "size": [10, 10, 10]},
        {"name": "b", "op": "box", "size": [10, 10, 10], "position": [20, 0, 0]},
        {"name": "u", "op": "union", "inputs": ["a", "b"]},
        {"name": "c", "op": "box", "size": [30, 10, 10]},
        {"name": "d", "op": "box", "size": [25, 10, 10]},
        {"name": "result", "op": "intersect", "inputs": ["u", "c", "d"]},
    ]
    parts, _ = construct(document(features))
    assert len(parts["part"].solids()) == 2
    assert parts["part"].volume == pytest.approx(1500)
    features[-1]["inputs"] = ["u", "c"]
    features.append({"name": "binary", "op": "intersect", "inputs": ["result", "d"]})
    split, _ = construct(document(features, "binary"))
    assert parts["part"].volume == pytest.approx(split["part"].volume)


def test_multi_subtraction_preserves_disconnected_pieces():
    parts, _ = construct(
        document(
            [
                {"name": "stock", "op": "box", "size": [30, 10, 10]},
                {"name": "middle", "op": "box", "size": [10, 12, 12], "position": [10, -1, -1]},
                {"name": "end", "op": "box", "size": [5, 12, 12], "position": [25, -1, -1]},
                {"name": "result", "op": "subtract", "inputs": ["stock", "middle", "end"]},
            ]
        )
    )
    assert len(parts["part"].solids()) == 2
    assert parts["part"].volume == pytest.approx(1500)


@pytest.mark.parametrize("op", ["subtract", "intersect"])
def test_empty_intermediate_has_useful_error(op):
    features = [
        {"name": "a", "op": "box", "size": [10, 10, 10]},
        {
            "name": "b",
            "op": "box",
            "size": [10, 10, 10],
            "position": [20 if op == "intersect" else 0, 0, 0],
        },
        {"name": "result", "op": op, "inputs": ["a", "b", "a"]},
    ]
    with pytest.raises(ValueError, match="valid non-empty solid"):
        construct(document(features))


@pytest.mark.parametrize("clockwise", [False, True])
@pytest.mark.parametrize("op", ["extrude", "extrude_z"])
def test_extrusion_direction_and_legacy_warning(op, clockwise):
    points = [[0, 0], [10, 0], [10, 10], [0, 10]]
    if clockwise:
        points.reverse()
    doc = document([{"name": "result", "op": op, "points": points, "height": 3}])
    parts, expr = construct(doc)
    bounds = parts["part"].bounding_box()
    legacy_down = op == "extrude" and clockwise
    assert bounds.min.Z == pytest.approx(-3 if legacy_down else 0)
    assert bounds.max.Z == pytest.approx(0 if legacy_down else 3)
    assert parts["part"].volume == pytest.approx(300)
    warnings = inspection(parts, doc, expr)["warnings"]
    assert bool(warnings) == legacy_down
    if legacy_down:
        assert warnings[0]["code"] == "legacy_clockwise_extrusion"


def test_explicit_extrusion_direction_precedes_placement():
    doc = document(
        [
            {
                "name": "result",
                "op": "extrude_z",
                "points": [[0, 10], [10, 10], [10, 0], [0, 0]],
                "height": 3,
                "rotation": [0, 90, 0],
                "position": [20, 0, 0],
            }
        ]
    )
    parts, _ = construct(doc)
    bounds = parts["part"].bounding_box()
    assert bounds.min.X == pytest.approx(20)
    assert bounds.max.X == pytest.approx(23)
