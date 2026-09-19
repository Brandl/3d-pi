"""Single connected analytic-boundary master: base, locating lip, filled flutes, collar.

No overlapping closed meshes or hidden internal faces; neighboring rings share
vertices. Cylinders and flute surface are sampled, not represented as exact STEP.
"""

import numpy as np

from cad.schema import Expressions


def dimensions(doc, surface):
    e = Expressions(doc.parameters)
    p = {
        key: e.value(getattr(doc.solid_master, key))
        for key in type(doc.solid_master).model_fields
        if key != "wide_end_down" and getattr(doc.solid_master, key) is not None
    }
    limits = {
        "collar_radius": (10, 250),
        "collar_height": (5, 60),
        "base_thickness": (1.5 if doc.captured_base else 2, 12),
        "base_overhang": (0 if doc.captured_base else 1, 15),
        "lip_height": (2, 10),
        "lip_thickness": (1.5, 6),
        "lip_clearance": (0.15, 1),
        "plaster_corner_chamfer": (0, 3),
        "pedestal_base_chamfer": (0, 6),
        "capture_shoulder": (0, 3),
        "tip_extension": (0, 20),
        "tip_transition": (0.5, 10),
        "tip_radius": (1, 200),
    }
    for key, (low, high) in limits.items():
        if not low <= p[key] <= high:
            raise ValueError(f"Solid master {key} must be in {low}..{high} mm")
    envelope = max(
        surface.bottom_radius + surface.bottom_amplitude, surface.top_radius + surface.top_amplitude
    )
    inner = envelope + e.value(doc.casting_box.plaster_clearance)
    wall = e.value(doc.casting_box.wall_thickness)
    outer = inner + (max(wall, 4) if doc.captured_base else wall)
    p.update(
        wide_end_down=doc.solid_master.wide_end_down,
        base_radius=outer + p["base_overhang"],
        lip_outer_radius=inner - p["lip_clearance"],
        lip_inner_radius=inner - p["lip_clearance"] - p["lip_thickness"],
        collar_to_wall_clearance=inner - p["collar_radius"],
    )
    if p["capture_shoulder"] and not doc.captured_base:
        raise ValueError("Capture shoulder requires a captured base")
    if p["plaster_corner_chamfer"] and (
        not doc.captured_base or p["plaster_corner_chamfer"] > p["lip_thickness"] - 0.5
    ):
        raise ValueError(
            "Plaster corner chamfer requires a captured base and at least 0.5 mm remaining lip land"
        )
    if not envelope + 0.5 <= p["collar_radius"] <= inner - 5:
        raise ValueError("Collar must cover the flutes and leave at least 5 mm to the walls")
    if not p["wide_end_down"] and p["collar_height"] < e.value(doc.casting_box.top_clearance):
        raise ValueError("Upright collar must reach the form's top")
    p["form_top_z"] = surface.height + e.value(doc.casting_box.top_clearance)
    p["master_top_z"] = surface.height + p["collar_height"] + p["tip_extension"]
    p["plaster_cover_above_master"] = p["form_top_z"] - p["master_top_z"]
    if p["lip_height"] >= surface.height or p["lip_inner_radius"] <= envelope + 2:
        raise ValueError("Locating lip must remain separated from the dripper")
    if p["wide_end_down"] and p["lip_inner_radius"] <= p["collar_radius"] + 0.5:
        raise ValueError("Wide-end collar must fit inside the locating lip with a gap")
    foot_chamfer = p["pedestal_base_chamfer"]
    if foot_chamfer and (
        not p["wide_end_down"]
        or foot_chamfer >= p["collar_height"]
        or p["collar_radius"] + foot_chamfer >= p["lip_inner_radius"] - 0.5
    ):
        raise ValueError(
            "Pedestal chamfer requires a wide-end-down master and clearance from the perimeter lip"
        )
    # At fixed theta: dr/du = R' + A' cos(phase) + A*N*T/H sin(phase).
    # A is largest at the wide end, so this is a GLOBAL lower bound, not
    # just a sampled draft test. After rigid inversion, radius decreases up Z.
    minimum_taper = (surface.top_radius - surface.bottom_radius) / surface.height - np.hypot(
        (surface.top_amplitude - surface.bottom_amplitude) / surface.height,
        surface.top_amplitude * surface.flute_count * surface.twist / surface.height,
    )
    if surface.profile == "origami":
        minimum_taper *= np.cos(np.pi / surface.flute_count)
    p["surface_profile"] = surface.profile
    p["minimum_flute_radial_taper"] = float(minimum_taper)
    p["axial_draw_no_undercut"] = bool(p["wide_end_down"] and minimum_taper >= 0)
    p["plaster_draw_direction"] = (
        "+Z away from base" if p["wide_end_down"] else "not certified with narrow-end base"
    )
    if p["tip_extension"]:
        if not p["wide_end_down"] or p["tip_transition"] > p["tip_extension"]:
            raise ValueError(
                "Tip extension requires wide-end-down orientation and a blend no longer than the extension"
            )
        delta_min = surface.bottom_radius - surface.bottom_amplitude - p["tip_radius"]
        if surface.profile == "origami":
            delta_min = (surface.bottom_radius - surface.bottom_amplitude) * np.cos(
                np.pi / surface.flute_count
            ) - p["tip_radius"]
        start_taper = (surface.top_radius - surface.bottom_radius) / surface.height
        variation = np.hypot(
            (surface.top_amplitude - surface.bottom_amplitude) / surface.height,
            surface.bottom_amplitude * surface.flute_count * surface.twist / surface.height,
        )
        # Cubic Hermite with zero end slope is monotone for normalized start slope 0..3.
        if (
            delta_min <= 0
            or start_taper - variation < 0
            or p["tip_transition"] * (start_taper + variation) / delta_min > 3
        ):
            raise ValueError(
                "Tip blend would risk an axial undercut; use a smaller end radius or shorter blend"
            )
        p["tip_blend_no_undercut"] = True
        p["tip_straight_length"] = p["tip_extension"] - p["tip_transition"]
    if doc.base_lock:
        from cad.base_lock import design

        p["base_lock"] = design(doc, surface, p)
    if doc.captured_base:
        from cad.captured_base import design

        p["captured_base"] = design(doc, surface, p)
    return p


def tip_surface(surface, p, theta, distance):
    """C1 Hermite blend from the rigidly inverted narrow end to a circular neck."""
    n = surface.flute_count
    phase = n * theta
    r0 = surface.bottom_radius + surface.bottom_amplitude * np.cos(phase)
    rp = -surface.bottom_amplitude * n * np.sin(phase)
    mean_slope = (surface.top_radius - surface.bottom_radius) / surface.height
    amp_slope = (surface.top_amplitude - surface.bottom_amplitude) / surface.height
    twist_slope = surface.bottom_amplitude * n * surface.twist / surface.height
    d0 = -mean_slope - amp_slope * np.cos(phase) + twist_slope * np.sin(phase)
    dp = amp_slope * n * np.sin(phase) + twist_slope * n * np.cos(phase)
    if surface.profile == "origami":
        r0, rp, ru, rup = surface.origami_radial(theta, 0)
        d0, dp = -ru, -rup
    length = p["tip_transition"]
    t = min(distance / length, 1)
    h0 = 2 * t**3 - 3 * t**2 + 1
    h1 = t**3 - 2 * t**2 + t
    h2 = -2 * t**3 + 3 * t**2
    radius = h0 * r0 + h1 * length * d0 + h2 * p["tip_radius"]
    rt = h0 * rp + h1 * length * dp
    rz = (
        (6 * t * t - 6 * t) * r0
        + (3 * t * t - 4 * t + 1) * length * d0
        + (-6 * t * t + 6 * t) * p["tip_radius"]
    ) / length
    c, s = np.cos(theta), np.sin(theta)
    points = np.column_stack(
        (
            radius * c,
            radius * s,
            np.full_like(theta, surface.height + p["collar_height"] + distance),
        )
    )
    normals = np.column_stack((radius * c + rt * s, radius * s - rt * c, -radius * rz))
    normals /= np.linalg.norm(normals, axis=1, keepdims=True)
    return points, normals


def sample(surface, p, angular, vertical):
    theta = np.arange(angular) * 2 * np.pi / angular
    xy = np.column_stack((np.cos(theta), np.sin(theta)))
    rings, ring_normals, circular = [], [], []

    def circle(radius, z):
        points = np.column_stack((radius * xy, np.full(angular, z)))
        if rings and np.allclose(points, rings[-1], atol=1e-10, rtol=0):
            return
        rings.append(points)
        ring_normals.append(np.column_stack((xy, np.zeros(angular))))
        circular.append(True)

    # Walk the OUTSIDE boundary from bottom edge up, over the lip, down its
    # inside, across the exposed base floor, up the flutes, and over the collar.
    circle(p["base_radius"], -p["base_thickness"])
    if p.get("captured_base"):
        joint = p["captured_base"]
        circle(joint["flange_radius"], joint["flange_chamfer_bottom_z"])
        if joint["capture_shoulder"]:
            circle(joint["flange_chamfer_top_radius"], joint["flange_chamfer_top_z"])
        circle(joint["core_radius"], joint["flange_chamfer_top_z"])
        if joint["flange_chamfer_top_z"] < 0:
            circle(joint["core_radius"], 0)
    else:
        circle(p["base_radius"], 0)
    if p.get("base_lock"):
        seal = p["base_lock"]
        circle(seal["groove_outer_radius"], 0)
        circle(seal["groove_outer_radius"], -seal["groove_depth"])
        circle(seal["groove_inner_radius"], -seal["groove_depth"])
        circle(seal["groove_inner_radius"], 0)
    if not p.get("captured_base") or p["captured_base"]["flange_chamfer_top_z"] <= 0:
        circle(p["lip_outer_radius"], 0)
    bevel_segments = set()
    chamfer = p.get("plaster_corner_chamfer", 0)
    if chamfer:
        bevel_segments.add(len(rings) - 1)
        circle(p["lip_outer_radius"], p["lip_height"] + chamfer)
        bevel_segments.add(len(rings) - 1)
        circle(p["lip_outer_radius"] - chamfer, p["lip_height"])
    else:
        circle(p["lip_outer_radius"], p["lip_height"])
    circle(p["lip_inner_radius"], p["lip_height"])
    circle(p["lip_inner_radius"], 0)
    inverted = p.get("wide_end_down", False)
    if inverted:
        foot_chamfer = p.get("pedestal_base_chamfer", 0)
        circle(p["collar_radius"] + foot_chamfer, 0)
        if foot_chamfer:
            bevel_segments.add(len(rings) - 1)
            circle(p["collar_radius"], foot_chamfer)
        circle(p["collar_radius"], p["collar_height"])
        body_start = len(rings)
        body_intervals = 1 if surface.profile == "origami" else vertical
        for z in np.linspace(surface.height, 0, body_intervals + 1):
            # A rigid 180-degree X rotation, NOT a mirror of the flutes.
            # Reverse angular sampling to keep each new XY ring CCW.
            points, normals = surface.exterior(-theta, z)
            points[:, 1] *= -1
            points[:, 2] = surface.height + p["collar_height"] - points[:, 2]
            normals[:, 1:] *= -1
            rings.append(points)
            ring_normals.append(normals)
            circular.append(False)
    else:
        for z in np.linspace(0, surface.height, vertical + 1):
            points, normals = surface.exterior(theta, z)
            rings.append(points)
            ring_normals.append(normals)
            circular.append(False)
        circle(p["collar_radius"], surface.height)
        circle(p["collar_radius"], surface.height + p["collar_height"])
    body_end = len(rings) - 1
    tip_edges = []
    if p.get("tip_extension", 0):
        tip_edges.append(len(rings) - 1)
        for distance in np.linspace(0, p["tip_transition"], 17)[1:]:
            points, normals = tip_surface(surface, p, theta, distance)
            rings.append(points)
            ring_normals.append(normals)
            circular.append(False)
        tip_edges.append(len(rings) - 1)
        if p["tip_extension"] > p["tip_transition"]:
            points, normals = tip_surface(surface, p, theta, p["tip_extension"])
            rings.append(points)
            ring_normals.append(normals)
            circular.append(False)
    panel_centers, panel_normals, panels = [], [], []
    if surface.profile == "origami":
        per_face = angular // (2 * surface.flute_count)
        for j in range(0, angular, per_face):
            end = (j + per_face) % angular
            corners = np.array(
                [
                    rings[body_start][j],
                    rings[body_start][end],
                    rings[body_end][end],
                    rings[body_end][j],
                ]
            )
            normal = np.cross(corners[1] - corners[0], corners[2] - corners[0])
            normal /= np.linalg.norm(normal)
            panel_centers.append(corners.mean(axis=0))
            panel_normals.append(normal)
            indices = [(j + i) % angular for i in range(per_face + 1)]
            panels.append(
                [body_start * angular + i for i in indices]
                + [body_end * angular + i for i in reversed(indices)]
            )
    vertices = np.concatenate(
        rings
        + [
            np.array(panel_centers).reshape(-1, 3),
            np.array([[0, 0, -p["base_thickness"]], [0, 0, p["master_top_z"]]]),
        ]
    )
    normals = np.concatenate(
        ring_normals + [np.array(panel_normals).reshape(-1, 3), np.array([[0, 0, -1], [0, 0, 1]])]
    )
    faces, flat = [], []
    # Surface normals remain discontinuous at all planar shoulders/caps.
    for k in range(len(rings) - 1):
        start = len(faces)
        if surface.profile == "origami" and k == body_start:
            # One explicit planar panel per crease interval. A center fan retains
            # every boundary node shared with the round pedestal/neck, without
            # numerically fragile grids of long coplanar sliver triangles.
            for index, perimeter in enumerate(panels):
                center = len(rings) * angular + index
                start = len(faces)
                for left, right in zip(perimeter, perimeter[1:] + perimeter[:1]):
                    faces.append((center, left, right))
                flat.append(
                    {
                        "start": start,
                        "count": len(perimeter),
                        "normal": panel_normals[index].tolist(),
                    }
                )
            continue
        for j in range(angular):
            nxt = (j + 1) % angular
            a, b, c, d = (
                k * angular + j,
                k * angular + nxt,
                (k + 1) * angular + nxt,
                (k + 1) * angular + j,
            )
            faces.extend(((a, b, c), (a, c, d)))
        dz = rings[k + 1][0, 2] - rings[k][0, 2]
        if abs(dz) < 1e-10:
            dr = (
                np.linalg.norm(rings[k + 1][:, :2], axis=1).mean()
                - np.linalg.norm(rings[k][:, :2], axis=1).mean()
            )
            flat.append(
                {"start": start, "count": 2 * angular, "normal": [0, 0, -1 if dr > 0 else 1]}
            )
        elif circular[k] and circular[k + 1]:
            # Cylindrical or conical sides. Planar shoulders retain hard normals.
            dr = np.linalg.norm(rings[k + 1][0, :2]) - np.linalg.norm(rings[k][0, :2])
            length = np.hypot(dr, dz)
            for index in (k, k + 1):
                normals[index * angular : (index + 1) * angular, :2] = xy * dz / length
                normals[index * angular : (index + 1) * angular, 2] = -dr / length
            if k in bevel_segments:
                # Keep the sharp circular crest separate from both adjacent faces.
                for j in range(angular):
                    angle = (j + 0.5) * 2 * np.pi / angular
                    flat.append(
                        {
                            "start": start + 2 * j,
                            "count": 2,
                            "normal": [
                                float(np.cos(angle) * dz / length),
                                float(np.sin(angle) * dz / length),
                                float(-dr / length),
                            ],
                        }
                    )
    bottom, top = len(vertices) - 2, len(vertices) - 1
    start = len(faces)
    for j in range(angular):
        nxt = (j + 1) % angular
        faces.append((bottom, nxt, j))
    flat.append({"start": start, "count": angular, "normal": [0, 0, -1]})
    start = len(faces)
    last = (len(rings) - 1) * angular
    for j in range(angular):
        faces.append((top, last + j, last + (j + 1) % angular))
    flat.append({"start": start, "count": angular, "normal": [0, 0, 1]})
    edges = []
    edge_rings = [
        k
        for k in range(len(rings))
        if circular[k]
        or k in tip_edges
        or k == len(rings) - 1
        or (k > 0 and circular[k - 1])
        or (k + 1 < len(rings) and circular[k + 1])
    ]
    for k in edge_rings:
        ring = rings[k]
        for a, b in zip(ring, np.roll(ring, -1, axis=0)):
            edges.extend((a.tolist(), b.tolist()))
    if surface.profile == "origami":
        for j in range(0, angular, angular // (2 * surface.flute_count)):
            edges.extend((rings[body_start][j].tolist(), rings[body_end][j].tolist()))
    return vertices, np.asarray(faces), normals, flat, edges
