"""Four external M5 screw clamps and a continuous base face seal.

The clamps and wall feet are printable. Bolts, nuts and the silicone ring are
purchased references, never offered as printable substitutes. This is geometric
fit validation, not a strength, preload or leak-tightness certification.
"""

import math

import build123d as b

from cad.schema import Expressions

ANGLES = {"base_clamp_ne": 45, "base_clamp_nw": 135, "base_clamp_sw": 225, "base_clamp_se": 315}
COLOR = "#65bdaa"
ALIGN = (b.Align.CENTER, b.Align.CENTER, b.Align.MIN)


def box(x, y, z, dx, dy, dz):
    return b.Pos(x, y, z) * b.Box(dx, dy, dz, align=(b.Align.MIN,) * 3)


def design(doc, surface, master):
    e = Expressions(doc.parameters)
    wall = e.value(doc.casting_box.wall_thickness)
    inner = max(
        surface.top_radius + surface.top_amplitude, surface.bottom_radius + surface.bottom_amplitude
    ) + e.value(doc.casting_box.plaster_clearance)
    outer = inner + wall
    base = master["base_radius"]
    if wall < 3.8 or master["base_thickness"] < 6 or master["base_overhang"] < 14:
        raise ValueError("Base clamps require walls >=3.8 mm, base >=6 mm, base overhang >=14 mm")
    return {
        "gasket_center_radius": inner + wall / 2,
        "gasket_cord_diameter": 2.0,
        "groove_width": 2.8,
        "groove_depth": 1.5,
        "groove_inner_radius": inner + wall / 2 - 1.4,
        "groove_outer_radius": inner + wall / 2 + 1.4,
        "nominal_gasket_squeeze_percent": 25,
        "groove_fill_percent": 100 * math.pi / (2.8 * 1.5),
        "inner_sealing_land": wall / 2 - 1.4,
        "outer_sealing_land": wall / 2 - 1.4,
        "oring_nominal_id": 2 * (inner + wall / 2) - 2,
        "oring_nominal_cross_section": 2,
        "foot_height": 6.0,
        "foot_width": 16.0,
        "foot_inner_radius": outer - 2,
        "foot_outer_x": base - 1,
        "screw_radius": outer + 7.5,
        "screw_clearance_diameter": 5.5,
        "clamp_inner_x": outer + 2,
        "clamp_spine_x": base + 0.6,
        "clamp_wall": 6.0,
        "clamp_width": 16.0,
        "clamp_roof_bottom": 14.0,
        "clamp_roof_top": 20.0,
        "nut_pocket_across_flats": 8.4,
        "nut_pocket_depth": 4.3,
        "clamp_count": 4,
        "hardware": "4 × M5×20 fully threaded screws + 4 × standard M5 hex nuts (8 mm AF, 4 mm thick)",
        "seal": "continuous 2 mm silicone O-ring/cord; nominal 25% squeeze; not printed plastic",
    }


def hexagon(across_flats, height):
    return b.extrude(b.RegularPolygon(across_flats / math.sqrt(3), 6), amount=height)


def modify_parts(parts, d, master):
    parts = {
        name: b.Compound(children=list(shape)) if isinstance(shape, (list, b.ShapeList)) else shape
        for name, shape in parts.items()
    }
    foot = box(d["foot_inner_radius"], -8, 0, d["foot_outer_x"] - d["foot_inner_radius"], 16, 6)
    for name, angle in ANGLES.items():
        wall = "wall_right" if math.cos(math.radians(angle)) > 0 else "wall_left"
        parts[wall] = parts[wall].fuse(b.Rot(0, 0, angle) * foot)
    lo, spine, width = d["clamp_inner_x"], d["clamp_spine_x"], d["clamp_wall"]
    bottom = -master["base_thickness"]
    clamp = box(lo, -8, bottom - width, spine + width - lo, 16, width).fuse(
        box(spine, -8, bottom - width, width, 16, 20 - bottom + width),
        box(lo, -8, 14, spine + width - lo, 16, 6),
    )
    hole = b.Pos(d["screw_radius"], 0, 13) * b.Cylinder(2.75, 8, align=ALIGN)
    pocket = b.Pos(d["screw_radius"], 0, 14) * hexagon(8.4, 4.3)
    clamp = clamp.cut(hole, pocket)
    for name, angle in ANGLES.items():
        parts[name] = b.Rot(0, 0, angle) * clamp
    return parts


def references(d):
    # Schematic, unthreaded purchased hardware, NOT printable functional screws.
    shaft = b.Pos(d["screw_radius"], 0, 6) * b.Cylinder(2.5, 20, align=ALIGN)
    head = b.Pos(d["screw_radius"], 0, 26) * hexagon(8, 3.5)
    nut = b.Pos(d["screw_radius"], 0, 14.3) * hexagon(8, 4)
    hardware = shaft.fuse(head, nut)
    result = {
        "m5_" + name.removeprefix("base_clamp_"): b.Rot(0, 0, angle) * hardware
        for name, angle in ANGLES.items()
    }
    # Equal-area elliptical compressed cross-section: approximate visualization
    # only, not a rubber constitutive model. Top and bottom contact seating faces.
    ellipse = b.Pos(d["gasket_center_radius"], 0, -0.75) * (b.Plane.XZ * b.Ellipse(4 / 3, 0.75))
    result["base_gasket"] = b.revolve(ellipse, axis=b.Axis.Z)
    return result


def gasket_mesh(d):
    """Bounded display mesh; native ellipse-revolve meshing is excessive."""
    import numpy as np

    n, m = 180, 24
    theta = np.arange(n)[:, None] * 2 * np.pi / n
    phi = np.arange(m)[None, :] * 2 * np.pi / m
    radius = d["gasket_center_radius"] + (4 / 3) * np.cos(phi)
    x = radius * np.cos(theta)
    y = radius * np.sin(theta)
    z = np.broadcast_to(-0.75 + 0.75 * np.sin(phi), (n, m))
    vertices = np.stack((x, y, z), axis=-1).reshape(-1, 3)
    faces = []
    for i in range(n):
        for j in range(m):
            a = i * m + j
            b = ((i + 1) % n) * m + j
            c = ((i + 1) % n) * m + (j + 1) % m
            d_ = i * m + (j + 1) % m
            faces.extend(((a, b, c), (a, c, d_)))
    return vertices, np.asarray(faces)


def checks(parts, refs, base, d, overlap):
    result = {
        "dimensions": d,
        "base_capture_interference_mm3": {},
        "screw_blocks_wall_lift_mm3": {},
        "clamp_removal_overlap_mm3": {},
        "purchased_hardware_interference_mm3": {},
    }
    for name, angle in ANGLES.items():
        clamp = parts[name]
        wall = "wall_right" if math.cos(math.radians(angle)) > 0 else "wall_left"
        hardware = refs["m5_" + name.removeprefix("base_clamp_")]
        capture = overlap(b.Pos(0, 0, 0.5) * clamp, base)
        restraint = overlap(b.Pos(0, 0, 0.5) * parts[wall], hardware)
        if min(capture, restraint) < 1e-4:
            raise ValueError("Base screw clamp does not capture both base and wall foot")
        result["base_capture_interference_mm3"][name] = capture
        result["screw_blocks_wall_lift_mm3"][name] = restraint
        # Remove loosened clamp radially outward. Screw must first clear foot.
        maximum = 0.0
        for distance in (0, 2, 10, 30):
            x = distance * math.cos(math.radians(angle))
            y = distance * math.sin(math.radians(angle))
            moved = b.Pos(x, y, 0) * clamp
            maximum = max(maximum, overlap(moved, base), overlap(moved, parts[wall]))
        result["clamp_removal_overlap_mm3"][name] = maximum
        interference = max(overlap(hardware, body) for body in [base, *parts.values()])
        result["purchased_hardware_interference_mm3"][name] = interference
    if (
        max(
            [
                *result["clamp_removal_overlap_mm3"].values(),
                *result["purchased_hardware_interference_mm3"].values(),
            ]
        )
        > 1e-5
    ):
        raise ValueError("Base clamp/hardware geometry interferes")
    gasket = refs["base_gasket"]
    result["gasket_interference_mm3"] = max(
        overlap(gasket, body) for body in [base, *parts.values()]
    )
    if result["gasket_interference_mm3"] > 1e-5:
        raise ValueError("Compressed gasket does not fit its seat")
    result["not_certified"] = [
        "clamp strength/preload",
        "FDM porosity",
        "liquid tightness",
        "rubber behavior",
    ]
    result["assembly"] = [
        d["hardware"]
        + f"; 1 × continuous silicone O-ring, ID {d['oring_nominal_id']:g} mm × 2 mm cross-section. Prefer soft silicone (about 40–50 Shore A). Use purchased hardware, not printed substitutes.",
        "If silicone cord is used instead of a seamless ring, bond and cure the butt joint with a compatible adhesive; an unjoined gap can leak.",
        "Install a continuous silicone O-ring in the clean base groove; do not substitute rigid printed plastic.",
        "Seat wall halves on the gasket around the lip and install both vertical dovetail locks.",
        "Fit an M5 nut into each underside hex pocket; insert an M5x20 screw from above.",
        "Slide the four clamps over the base edge/feet. Hand-tighten opposing screws gradually and evenly until the wall bottoms seat on the base lands. Do not over-torque.",
        "Seal BOTH full-height wall split seams with compatible removable clay/putty or tape. The dovetail clips locate/retain; they are not liquid seals.",
        "Check printed walls/master for porosity, seal as needed, and water-test at the intended fill height before plaster. A clamp is not a leakage guarantee.",
        "After setting, loosen screws until tips clear the feet by at least 2 mm; withdraw clamps radially outward, remove dovetail locks, then wall halves. Lift plaster upward off the master.",
    ]
    return result
