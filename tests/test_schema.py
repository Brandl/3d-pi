import pytest
from pydantic import ValidationError

from cad.schema import Document, Expressions


def box_document():
    return {
        "name": "Test box",
        "parameters": {"width": 20},
        "features": [{"name": "block", "op": "box", "size": ["width", 10, 5]}],
        "outputs": [{"name": "block", "feature": "block"}],
        "sections": [{"name": "profile", "part": "block", "z": 2}],
        "checks": [{"part": "block", "metric": "x", "expected": "width"}],
    }


def test_parameter_dependencies():
    expr = Expressions({"inner": "width-2*wall", "width": 80, "wall": 2.4})
    assert expr.value("inner/2") == pytest.approx(37.6)


@pytest.mark.parametrize(
    "source",
    [
        "__import__('os').system('id')",
        "(1).__class__",
        "2**1000",
        "[1][0]",
        "1/0",
        "1e999",
        "unknown",
        "True",
    ],
)
def test_reject_unsafe_or_invalid_expressions(source):
    with pytest.raises((ValueError, ZeroDivisionError)):
        Expressions({}).value(source)


def test_cycle():
    with pytest.raises(ValueError, match="cyclic"):
        Expressions({"a": "b", "b": "a"})


@pytest.mark.parametrize(
    "change",
    [
        {"schema_version": 2},
        {"units": "inch"},
        {"python": "print('bad')"},
        {"linear_tolerance": 0.00001},
        {"parameters": {"../../etc": 2}},
        {"features": [{"name": "a", "op": "transform", "inputs": ["missing"]}]},
        {"features": [{"name": "a", "op": "box", "size": [1, 2, 3], "radius": 5}]},
    ],
)
def test_invalid_documents(change):
    with pytest.raises(ValidationError):
        Document.model_validate({**box_document(), **change})
