"""Self-contained teaching geometry; no dependency on personal example files."""


def enclosure_document():
    """Return a fresh editable document, not a saved or manufacturing-approved design."""
    features = [
        {"name": "outer", "op": "box", "size": ["width", "depth", "height"]},
        {
            "name": "cavity",
            "op": "box",
            "size": ["width-2*wall", "depth-2*wall", "height"],
            "position": ["wall", "wall", "wall"],
        },
        {"name": "shell", "op": "subtract", "inputs": ["outer", "cavity"]},
        {"name": "lid_blank", "op": "box", "size": ["width", "depth", "lid_thickness"]},
    ]
    holes = []
    for i, (x, y) in enumerate(
        [
            ("hole_offset", "hole_offset"),
            ("width-hole_offset", "hole_offset"),
            ("hole_offset", "depth-hole_offset"),
            ("width-hole_offset", "depth-hole_offset"),
        ]
    ):
        name = f"hole_{i}"
        holes.append(name)
        features.append(
            {
                "name": name,
                "op": "cylinder",
                "radius": "hole_radius",
                "height": "height+lid_thickness+2",
                "position": [x, y, -1],
            }
        )
    features.extend(
        [
            {"name": "body", "op": "subtract", "inputs": ["shell", *holes]},
            {"name": "lid_cut", "op": "subtract", "inputs": ["lid_blank", *holes]},
            {
                "name": "lid_beside",
                "op": "transform",
                "inputs": ["lid_cut"],
                "position": ["width+gap", 0, 0],
            },
        ]
    )
    return {
        "schema_version": 1,
        "name": "Teaching enclosure and lid",
        "units": "mm",
        "parameters": {
            "width": 72,
            "depth": 50,
            "height": 24,
            "wall": 2,
            "lid_thickness": 3,
            "hole_radius": 1.5,
            "hole_offset": 8,
            "gap": 12,
        },
        "features": features,
        "outputs": [
            {"name": "enclosure", "feature": "body", "color": "#6594ba"},
            {"name": "lid", "feature": "lid_beside", "color": "#d9a568"},
        ],
        "sections": [{"name": "lid_profile", "part": "lid", "z": "lid_thickness/2"}],
        "checks": [
            {"part": "enclosure", "metric": "x", "expected": "width"},
            {"part": "enclosure", "metric": "y", "expected": "depth"},
            {"part": "enclosure", "metric": "z", "expected": "height"},
            {"part": "enclosure", "metric": "solid_count", "expected": 1},
            {"part": "lid", "metric": "solid_count", "expected": 1},
        ],
    }
