"""Shared runtime limits used by validation and agent discovery."""

CASTING_BOX_LIMITS = {
    "plaster_clearance": (5, 60),
    "wall_thickness": (1.5, 10),
    "top_clearance": (0, 60),
    "rail_depth": (4, 15),
    "rail_half_width": (4, 15),
    "rail_top_margin": (5, 30),
    "rail_bottom_chamfer": (0, 6),
    "lock_wall": (1.5, 6),
    "lock_clearance": (0.15, 1),
    "lock_length": (20, 150),
}


def capabilities():
    return {
        "schema_version": 1,
        "tool_contract_version": 2,
        "tree_schema_version": 1,
        "units": "mm",
        "casting_box_limits_mm": {
            key: {"min": lo, "max": hi} for key, (lo, hi) in CASTING_BOX_LIMITS.items()
        },
        "constraints": [
            "Non-captured forms require wall_thickness >= 2 mm.",
            "Lock length must fit the rail; rail-top margin must exceed lock-cap thickness.",
            "Wall rim Z = surface body height + top_clearance. This parameter is NOT the actual plaster cover above an extended/pedestalled master; read the built report.",
            "These are casting-box limits, not a complete list of geometric/analytical constraints. Candidate validation remains required.",
        ],
        "workflow": ["inspect", "build candidate", "validate and render", "explicit publish"],
        "supported_exports": ["stl", "3mf", "step", "dxf", "zip"],
        "export_notes": "Availability is revision-specific. Analytic masters have no STEP; DXF requires named XY sections.",
        "scope": "One legacy design; no project selection or installed versioned component instances yet.",
        "execution": "Declarative CAD only. The agent has no deployment permission; workspace source edits do not update the running service.",
    }
