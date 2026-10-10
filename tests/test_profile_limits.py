import math

import pytest
from pydantic import ValidationError

from cad.schema import Document


def document(count, profiles=1):
    points = [
        (math.cos(i * math.tau / count), math.sin(i * math.tau / count)) for i in range(count)
    ]
    return {
        "features": [
            {"name": f"profile{i}", "op": "extrude_z", "points": points, "height": 1}
            for i in range(profiles)
        ],
        "outputs": [{"name": "part", "feature": "profile0"}],
    }


def test_profile_limits_are_bounded_individually_and_in_total():
    assert len(Document.model_validate(document(512)).features[0].points) == 512
    with pytest.raises(ValidationError):
        Document.model_validate(document(513))
    assert len(Document.model_validate(document(512, 4)).features) == 4
    with pytest.raises(ValidationError, match="2048"):
        Document.model_validate(document(512, 5))
