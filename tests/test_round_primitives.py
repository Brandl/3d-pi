import math

import pytest
from pydantic import ValidationError

from cad.geometry import construct
from cad.schema import Document


def model(features):
    return Document.model_validate(
        dict(
            schema_version=1,
            name="Round cutters",
            units="mm",
            parameters={},
            features=features,
            outputs=[dict(name="part", feature=features[-1]["name"])],
        )
    )


def test_sphere_is_centered_and_exact():
    parts, _ = construct(model([dict(name="ball", op="sphere", radius=12, position=[1, 2, 3])]))
    shape = parts["part"]
    assert shape.volume == pytest.approx(4 / 3 * math.pi * 12**3)
    assert list(shape.bounding_box().min) == pytest.approx([-11, -10, -9])
    assert list(shape.bounding_box().max) == pytest.approx([13, 14, 15])


def test_ball_subtraction_and_45_degree_chamfer():
    features = [
        dict(name="blank", op="cylinder", radius=10, height=6),
        dict(name="rim_limit", op="cone", size=[15, 9, 6]),
        dict(name="bevel", op="intersect", inputs=["blank", "rim_limit"]),
    ]
    parts, _ = construct(model(features))
    assert parts["part"].volume == pytest.approx(math.pi * (500 + 271 / 3))
    features += [
        dict(name="thumb_ball", op="sphere", radius=12, position=[0, 0, 16]),
        dict(name="button", op="subtract", inputs=["bevel", "thumb_ball"]),
    ]
    parts, _ = construct(model(features))
    assert parts["part"].is_valid and len(parts["part"].solids()) == 1
    cap_volume = math.pi * 2**2 * (12 - 2 / 3)
    assert parts["part"].volume == pytest.approx(math.pi * (500 + 271 / 3) - cap_volume)


@pytest.mark.parametrize(
    "feature",
    [
        dict(name="a", op="sphere"),
        dict(name="a", op="sphere", radius=2, height=3),
        dict(name="a", op="cone", radius=2, height=3),
        dict(name="a", op="cone", size=[1, 2, 3], inputs=["other"]),
    ],
)
def test_round_operands_are_strict(feature):
    with pytest.raises(ValidationError):
        model([feature])


@pytest.mark.parametrize(
    "feature",
    [
        dict(name="a", op="sphere", radius=-1),
        dict(name="a", op="sphere", radius=2001),
        dict(name="a", op="cone", size=[0, 0, 1]),
        dict(name="a", op="cone", size=[1, -1, 1]),
        dict(name="a", op="cone", size=[1, 2, 0]),
        dict(name="a", op="cone", size=[2001, 2, 1]),
    ],
)
def test_round_dimensions_are_bounded(feature):
    with pytest.raises(ValueError):
        construct(model([feature]))
