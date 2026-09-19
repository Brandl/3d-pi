"""Dry, weight-seated captured flange. No gasket, screws or separate base clamps.

A broad horizontal seat carries downward floor load. A parallel 45-degree
upper channel captures the flange. An optional flat retaining shoulder provides
a non-wedging lift stop, at the cost of a small horizontal print overhang.
The existing dovetail clips retain the wall halves; open them sideways to release.
"""

import math

import build123d as b

from cad.schema import Expressions

ALIGN = (b.Align.CENTER, b.Align.CENTER, b.Align.MIN)


def design(doc, surface, master):
    e = Expressions(doc.parameters)
    inner = max(
        surface.top_radius + surface.top_amplitude, surface.bottom_radius + surface.bottom_amplitude
    ) + e.value(doc.casting_box.plaster_clearance)
    wall = e.value(doc.casting_box.wall_thickness)
    outer = inner + max(wall, 4)
    if master["base_overhang"] != 0 or master["base_thickness"] < 1.5 or wall < 1.5:
        raise ValueError("Captured base requires zero overhang and floor/walls at least 1.5 mm")
    floor = -master["base_thickness"]
    flange = outer
    core = master["lip_outer_radius"]
    # Flange has a 1 mm outer land, then a 45 degree top chamfer up to the core.
    chamfer_bottom = floor + 1
    shoulder = master.get("capture_shoulder", 0)
    bevel_end = inner + shoulder if shoulder else core
    if shoulder and (not 0 < shoulder <= 3 or bevel_end >= flange - 0.5):
        raise ValueError("Capture shoulder must leave at least 0.5 mm of outer ramp")
    chamfer_top = chamfer_bottom + flange - bevel_end
    if chamfer_top > master["lip_height"] - 0.5:
        raise ValueError(
            "Raise the reinforced lip or increase floor thickness to accommodate the flange bevel"
        )
    normal_gap = master.get("capture_normal_clearance")
    if normal_gap is not None and not 0.15 <= normal_gap <= 1:
        raise ValueError("Capture normal clearance must be in 0.15..1 mm")
    radial_gap = 0.3 if normal_gap is None else normal_gap
    vertical_gap = 0.3 if normal_gap is None else normal_gap * math.sqrt(2)
    slot = flange + radial_gap
    roof_outer = chamfer_bottom + vertical_gap - radial_gap
    old_roof_inner = roof_outer + slot - inner
    shoulder_gap = normal_gap if normal_gap is not None else vertical_gap / math.sqrt(2)
    roof_inner = chamfer_top + shoulder_gap if shoulder else old_roof_inner
    roof_join = slot - (roof_inner - roof_outer) if shoulder else inner
    return {
        "capture_shoulder": shoulder,
        "flange_chamfer_top_radius": bevel_end,
        "channel_roof_join_radius": roof_join,
        "shoulder_vertical_clearance": shoulder_gap if shoulder else None,
        "horizontal_roof_overhang": roof_join - inner if shoulder else 0,
        "flange_radius": flange,
        "core_radius": core,
        "seat_z": floor,
        "seat_inner_radius": inner - 3,
        "seat_outer_radius": flange,
        "seat_width": flange - (inner - 3),
        "seat_area_mm2": math.pi * (flange**2 - (inner - 3) ** 2),
        "flange_chamfer_bottom_z": chamfer_bottom,
        "flange_chamfer_top_z": chamfer_top,
        "channel_outer_radius": slot,
        "channel_roof_outer_z": roof_outer,
        "channel_roof_inner_z": roof_inner,
        "radial_clearance": radial_gap,
        "normal_capture_clearance": vertical_gap / math.sqrt(2),
        "flat_floor_thickness": master["base_thickness"],
        "curved_wall_thickness": wall,
        "local_reinforcement_height": master["base_thickness"] + master["lip_height"],
        "vertical_capture_clearance": vertical_gap,
        "upper_chamfer_degrees": 45,
        "collar_outer_radius": slot + 5.7,
        "collar_bottom_z": floor - 4,
        "collar_top_z": max(4.0, roof_outer + slot - inner + 2),
        "wall_inner_radius": inner,
        "plaster_corner_chamfer": master.get("plaster_corner_chamfer", 0),
        "chamfer_former_peak_z": master["lip_height"] + master.get("plaster_corner_chamfer", 0),
        "hardware_required": False,
        "gasket_required": False,
    }


def roof_points(d):
    """Channel roof from outer pocket to inner wall; optional flat catch."""
    points = [(d["channel_outer_radius"], d["channel_roof_outer_z"])]
    if d.get("capture_shoulder"):
        points.append((d["channel_roof_join_radius"], d["channel_roof_inner_z"]))
    points.append((d["wall_inner_radius"], d["channel_roof_inner_z"]))
    return points


def collar(d):
    profile = b.Plane.XZ * b.Polygon(
        (d["seat_inner_radius"], d["collar_bottom_z"]),
        (d["collar_outer_radius"], d["collar_bottom_z"]),
        (d["collar_outer_radius"], d["collar_top_z"]),
        (d["wall_inner_radius"], d["collar_top_z"]),
        *reversed(roof_points(d)),
        (d["channel_outer_radius"], d["seat_z"]),
        (d["seat_inner_radius"], d["seat_z"]),
        align=None,
    )
    return b.revolve(profile, axis=b.Axis.Z)


def channel_void(d):
    profile = b.Plane.XZ * b.Polygon(
        (0, d["seat_z"]),
        (d["channel_outer_radius"], d["seat_z"]),
        *roof_points(d),
        (0, d["channel_roof_inner_z"]),
        align=None,
    )
    return b.revolve(profile, axis=b.Axis.Z)


def master_base(m, d):
    core = b.Pos(0, 0, d["seat_z"]) * b.Cylinder(d["core_radius"], m["base_thickness"], align=ALIGN)
    rim = b.Pos(0, 0, d["seat_z"]) * b.Cylinder(d["flange_radius"], 1, align=ALIGN)
    taper = b.Pos(0, 0, d["flange_chamfer_bottom_z"]) * b.Cone(
        d["flange_radius"],
        d["flange_chamfer_top_radius"],
        d["flange_chamfer_top_z"] - d["flange_chamfer_bottom_z"],
        align=ALIGN,
    )
    base = core.fuse(rim, taper)
    if d["flange_chamfer_top_z"] > 0:
        base = base.cut(b.Cylinder(m["lip_inner_radius"], m["lip_height"] + 1, align=ALIGN))
    return base


def section_svg(m, d):
    """Explanatory radial section, not an additional printable part."""
    foot = m.get("pedestal_base_chamfer", 0)
    start = m["collar_radius"] - 2 if foot else m["collar_radius"] + 1

    def point(r, z):
        return f"{30 + 12 * (r - start):.2f},{30 + 12 * (6 - z):.2f}"

    def polygon(points, color):
        return (
            '<polygon points="'
            + " ".join(point(r, z) for r, z in points)
            + '" fill="'
            + color
            + '" stroke="#243648" stroke-width="1.5"/>'
        )

    wall = [
        (d["seat_inner_radius"], d["collar_bottom_z"]),
        (d["collar_outer_radius"], d["collar_bottom_z"]),
        (d["collar_outer_radius"], d["collar_top_z"]),
        (d["wall_inner_radius"], d["collar_top_z"]),
        *reversed(roof_points(d)),
        (d["channel_outer_radius"], d["seat_z"]),
        (d["seat_inner_radius"], d["seat_z"]),
    ]
    floor = [
        (start, d["seat_z"]),
        (d["flange_radius"], d["seat_z"]),
        (d["flange_radius"], d["flange_chamfer_bottom_z"]),
        (d["core_radius"], d["flange_chamfer_top_z"]),
        (d["core_radius"], m["lip_height"] + m.get("plaster_corner_chamfer", 0)),
        (d["core_radius"] - m.get("plaster_corner_chamfer", 0), m["lip_height"]),
        (m["lip_inner_radius"], m["lip_height"]),
        (m["lip_inner_radius"], 0),
        (start, 0),
    ]
    if d.get("capture_shoulder"):
        floor.insert(3, (d["flange_chamfer_top_radius"], d["flange_chamfer_top_z"]))
    if foot:
        floor[-1:] = [
            (m["collar_radius"] + foot, 0),
            (m["collar_radius"], foot),
            (m["collar_radius"], 6),
            (start, 6),
        ]
    arrow_r = m["collar_radius"] + foot + 2 if foot else start + 4
    a = point(arrow_r, 3).split(",")
    b_ = point(arrow_r, d["seat_z"] + 0.5).split(",")
    seat_a = point(d["seat_inner_radius"], d["seat_z"]).split(",")
    seat_b = point(d["seat_outer_radius"], d["seat_z"]).split(",")
    width = max(580, 70 + 12 * (d["collar_outer_radius"] - start))
    catch_label = ""
    if d.get("capture_shoulder"):
        left = point(d["wall_inner_radius"], d["channel_roof_inner_z"]).split(",")
        right = point(d["flange_chamfer_top_radius"], d["channel_roof_inner_z"]).split(",")
        catch_label = f'''<line x1="{left[0]}" y1="{left[1]}" x2="{right[0]}" y2="{right[1]}" stroke="#c0392b" stroke-width="3"/>
<text x="18" y="235" font-family="sans-serif" font-size="13" fill="#c0392b">Red: {d["capture_shoulder"]:g} mm flat retaining shoulder; {d["shoulder_vertical_clearance"]:g} mm lift clearance.</text>'''
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} 340">
<rect width="100%" height="100%" fill="#fff"/>
<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 Z" fill="#20633a"/></marker></defs>
<text x="18" y="20" font-family="sans-serif" font-size="15">Captured dry floor joint - radial section</text>
{polygon(wall, "#75aadd")}{polygon(floor, "#f1e5ce")}
{catch_label}
<line x1="{a[0]}" y1="{a[1]}" x2="{b_[0]}" y2="{b_[1]}" stroke="#20633a" stroke-width="3" marker-end="url(#arrow)"/>
<line x1="{seat_a[0]}" y1="{seat_a[1]}" x2="{seat_b[0]}" y2="{seat_b[1]}" stroke="#20633a" stroke-width="3"/>
<g font-family="sans-serif" font-size="13" fill="#243648">
<text x="18" y="260">Ivory: integral floor flange. Blue: one wall half/channel.</text>
<text x="18" y="280">Green: downward load and {d["seat_width"]:g} mm-wide horizontal contact seat.</text>
<text x="18" y="300">Capture roof: {d["normal_capture_clearance"]:.3g} mm normal gap ({d["vertical_capture_clearance"]:.3g} mm vertical).</text>
<text x="18" y="320">No gasket or screws. Test the dry seal before pouring plaster.</text>
</g></svg>'''


def checks(parts, base, d, overlap):
    support = {}
    capture = {}
    withdraw = {}
    flat_capture = {}
    for name, sign in (("wall_left", -1), ("wall_right", 1)):
        wall = parts[name]
        support[name] = overlap(b.Pos(0, 0, -0.25) * base, wall)
        capture[name] = overlap(b.Pos(0, 0, 0.6) * base, wall)
        if d.get("capture_shoulder"):
            lift = (d["shoulder_vertical_clearance"] + d["vertical_capture_clearance"]) / 2
            flat_capture[name] = overlap(b.Pos(0, 0, lift) * base, wall)
            if flat_capture[name] <= 1e-5:
                raise ValueError("Flat shoulder must retain the floor before the ramp touches")
        for shift in (0, 0.3, 2, 10, 30):
            withdraw[f"{name}:{shift}mm"] = overlap(base, b.Pos(sign * shift, 0, 0) * wall)
    if min([*support.values(), *capture.values()]) <= 1e-5 or max(withdraw.values()) > 1e-5:
        raise ValueError("Captured floor lacks retention or cannot be removed sideways")
    return {
        "dimensions": d,
        "downward_floor_support_interference_mm3": support,
        "upward_floor_capture_interference_mm3": capture,
        "flat_shoulder_capture_interference_mm3": flat_capture,
        "sideways_wall_withdrawal_overlap_mm3": withdraw,
        "seal_contact": "broad annular horizontal plastic-on-plastic seat; floor rests on the lower ledge",
        "load_direction": "downward plaster weight adds compressive contact at the seat, without a downward-load wedge that spreads the walls",
        "leak_tightness_verified": False,
        "assembly": [
            f"Curved wall and flat floor: {d['curved_wall_thickness']:g} mm / {d['flat_floor_thickness']:g} mm. Rim and rails remain locally reinforced. Capture: {d['radial_clearance']:g} mm radial, {d['normal_capture_clearance']:.6g} mm normal to bevel; the horizontal loaded seat has zero gap.",
            "All parts are printed: master/flanged floor, two channeled wall halves and two existing slide locks. No gasket, screws, nuts or external clamps.",
            (
                f"Positive flat retaining shoulder: {d['capture_shoulder']:g} mm radial overlap, {d['shoulder_vertical_clearance']:g} mm vertical clearance. Upper horizontal faces stop lift before the bevel contacts. Test-print the {d['horizontal_roof_overhang']:.3g} mm horizontal roof overhang; add local removable supports if needed."
                if d.get("capture_shoulder")
                else "Tapered upper flange capture; no flat shoulder."
            ),
            f"Plaster corner former: {d['plaster_corner_chamfer']:g} mm at 45 degrees, integral with the base perimeter. The locating clearance is retained; any thin casting flash there may need trimming.",
            "Bring the halves around the floor flange so it enters both channels. Press the floor fully down onto the lower seat and close both halves before sliding down the locks.",
            "Keep the flat seat and flange underside clean and flat. The plaster weight loads this contact; the upper chamfer is a capture/printability feature, not the sealing face.",
            "Use a smooth build-plate face for the floor underside; print flat seating ledges carefully and remove burrs or high spots. Fit-test the joint before the complete print.",
            "The two vertical seams remain dry butt joints. Their print accuracy and the sliding locks affect leakage; this model does not claim that printed joints are inherently watertight.",
            "Water-test the dry assembly before plaster, checking the floor seat, split seams and printed surfaces. Avoid lifting or rocking the filled form, which can unload the seat.",
            "After setting, remove the two slide locks and move the wall halves sideways to free the captured floor. Then lift plaster upward off the wide-end-down master.",
        ],
    }
