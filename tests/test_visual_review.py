import copy

import numpy as np
from PIL import Image

from cad.geometry import render


def test_review_uses_distinct_part_colours_without_mutating_preview(tmp_path):
    tetra = {
        "name": "first",
        "color": "#888888",
        "vertices": [[0, 0, 0], [10, 0, 0], [0, 10, 0], [0, 0, 10]],
        "triangles": [[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]],
        "edges": [],
    }
    second = copy.deepcopy(tetra)
    second["name"] = "second"
    second["vertices"] = [[x + 15, y, z] for x, y, z in second["vertices"]]
    mesh = {"parts": [tetra, second]}
    original = copy.deepcopy(mesh)
    render(mesh, tmp_path, views=[("iso", 30, -55)])
    assert mesh == original
    assert (tmp_path / "render-iso.png").is_file()
    pixels = np.array(Image.open(tmp_path / "review-iso.png").convert("RGB"))
    # The unshaded legend preserves exact categorical colours, even though both
    # source parts requested the same grey and shaded faces vary with lighting.
    for colour in [(31, 119, 180), (255, 127, 14)]:
        assert np.count_nonzero(np.all(pixels == colour, axis=2)) > 10


def test_review_framing_keeps_projected_cube_inside_viewport(tmp_path, monkeypatch):
    from mpl_toolkits.mplot3d import Axes3D, proj3d
    import trimesh

    cube = trimesh.creation.box(extents=[100, 100, 100])
    mesh = {
        "parts": [
            {
                "name": "cube",
                "color": "#888888",
                "vertices": cube.vertices.tolist(),
                "triangles": cube.faces.tolist(),
                "edges": [],
            }
        ]
    }
    original = Axes3D.set_axis_off
    checks = []

    def check(ax):
        if len(ax.collections):
            x, y, _ = proj3d.proj_transform(*cube.vertices.T, ax.get_proj())
            bounds = ax.bbox.transformed(ax.transData.inverted())
            checks.append(
                x.min() >= bounds.x0
                and x.max() <= bounds.x1
                and y.min() >= bounds.y0
                and y.max() <= bounds.y1
            )
        original(ax)

    monkeypatch.setattr(Axes3D, "set_axis_off", check)
    render(mesh, tmp_path, views=[("iso", 30, -55)], review=True)
    assert checks and all(checks)
