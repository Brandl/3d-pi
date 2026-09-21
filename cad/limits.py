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
        "tool_contract_version": 4,
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
        "design_commits": {
            "tool": "cad_commit", "required_metadata": ["name", "icon", "source_file"],
            "generation": "workspace.generation, separate from publication generation",
            "outputs": "cad_attach links inspection/print/test artifacts without changing the working design",
            "source": "Clean Git HEAD document must exactly match normalized immutable CAD source",
        },
        "visual_review": {
            "views": ["iso", "top", "front", "exploded when available"],
            "styles": ["inspection", "standard"],
            "hidden_lines": False,
            "note": "New builds include inspection-colour PNGs; older revisions retain their original images. Agent checkpoints attach images, not automatic approval.",
        },
        "supported_exports": ["stl", "3mf", "step", "dxf", "zip"],
        "export_notes": "Availability is revision-specific. Analytic masters have no STEP; DXF requires named XY sections.",
        "scope": "One working design per project; explicit named/icon-labelled commits and related outputs. No installed versioned component instances.",
        "execution": "Declarative CAD only. The agent has no deployment permission; workspace source edits do not update the running service.",
    }
