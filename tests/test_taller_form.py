from local_examples import load_local_example

import pytest

from cad.casting_box import build
from cad.gentle_twist import Surface
from cad.schema import Document


def origami():
    return Document.model_validate(load_local_example("origami-20-locking-base"))


def test_sixty_mm_top_clearance_preserves_joint_checks():
    document = origami()
    document.parameters["mold_top_clearance"] = 60
    tooling = build(document, Surface.from_document(document)[0])
    assert tooling.dimensions["wall_height"] == 138
    assert tooling.dimensions["inner_diameter"] == 168
    assert tooling.dimensions["lock_length"] == 100
    assert all(part.is_valid for part in tooling.parts.values())
    assert max(tooling.checks["assembled_pair_overlap_mm3"].values()) < 1e-6
    assert tooling.checks["maximum_sampled_slide_overlap_mm3"] < 1e-6
    assert min(tooling.checks["spread_2mm_retention_interference_mm3"].values()) > 100


@pytest.mark.parametrize("value", [-0.01, 60.01])
def test_top_clearance_remains_bounded(value):
    document = origami()
    document.parameters["mold_top_clearance"] = value
    with pytest.raises(ValueError, match="top_clearance must be in 0..60"):
        build(document, Surface.from_document(document)[0])
