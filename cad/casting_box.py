"""Reusable outer plaster-casting formwork, not a production slip-casting mold.

Two rectangular U halves or semicircular halves meet at X=0. Paired triangular rails create
an undercut dovetail. Closed-top C-section clips slide DOWN along Z over them.
No base, mold cavity, master, parting surface, or shrinkage factor is invented.
"""

import json
import math
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import build123d as b
import lib3mf
import numpy as np
import trimesh

from cad.schema import Document, Expressions


@dataclass
class Tooling:
    parts: dict
    print_parts: dict
    dimensions: dict
    checks: dict
    references: dict = field(default_factory=dict)


COLORS = {
    "wall_left": "#75aadd",
    "wall_right": "#d6a076",
    "lock_front": "#df7656",
    "lock_back": "#df7656",
}


def box(x, y, z, dx, dy, dz):
    return b.Pos(x, y, z) * b.Box(dx, dy, dz, align=(b.Align.MIN,) * 3)


def overlap(a, c):
    # Intersect the actual solids: Compound.intersect can return None even when
    # its child solid overlaps the other body in the current build123d version.
    volume = 0.0
    for first in a.solids():
        for second in c.solids():
            common = first.intersect(second)
            if common is None:
                continue
            pieces = list(common) if isinstance(common, (list, b.ShapeList)) else [common]
            volume += sum(abs(s.volume) for piece in pieces for s in piece.solids())
    return volume


def build(doc: Document, surface) -> Tooling:
    config = doc.casting_box
    e = Expressions(doc.parameters)
    p = {
        name: e.value(getattr(config, name))
        for name in type(config).model_fields
        if name != "profile"
    }
    from cad.limits import CASTING_BOX_LIMITS

    limits = {**CASTING_BOX_LIMITS, "wall_thickness": (1.5 if doc.captured_base else 2, 10)}
    for key, (lo, hi) in limits.items():
        if not lo <= p[key] <= hi:
            raise ValueError(f"Casting box {key} must be in {lo}..{hi} mm")
    wall = p["wall_thickness"]
    # Circumscribed radius guarantees at least the specified lateral space,
    # regardless of the phase of the flutes at the top.
    envelope = max(
        surface.bottom_radius + surface.bottom_amplitude, surface.top_radius + surface.top_amplitude
    )
    inner = envelope + p["plaster_clearance"]
    outer = inner + wall
    rail_outer = inner + max(wall, 4) if doc.captured_base else outer
    height = surface.height + p["top_clearance"]
    rail_height = height - p["rail_top_margin"]
    depth, half_width = p["rail_depth"], p["rail_half_width"]
    clearance, skin = p["lock_clearance"], p["lock_wall"]
    length = p["lock_length"]
    if not 0 < length <= rail_height or p["rail_top_margin"] <= skin:
        raise ValueError(
            "Lock length must fit the rail; rail-top margin must exceed lock-cap thickness"
        )
    if config.profile == "round":
        ring = b.Cylinder(outer, height, align=(b.Align.CENTER, b.Align.CENTER, b.Align.MIN)).cut(
            b.Pos(0, 0, -1)
            * b.Cylinder(inner, height + 2, align=(b.Align.CENTER, b.Align.CENTER, b.Align.MIN))
        )
    else:
        ring = box(-outer, -outer, 0, 2 * outer, 2 * outer, height).cut(
            box(-inner, -inner, -1, 2 * inner, 2 * inner, height + 2)
        )
    captured = None
    extent, minimum_z = outer, -1
    if doc.captured_base:
        from cad.captured_base import collar
        from cad.solid_master import dimensions as master_dimensions

        captured = master_dimensions(doc, surface)["captured_base"]
        ring = ring.fuse(collar(captured))
        extent = max(extent, captured["collar_outer_radius"])
        minimum_z = captured["collar_bottom_z"] - 1
    # Each rail is a triangle whose tip reaches the inner wall face. Only its
    # outer widening portion protrudes: no triangular imprint inside the plaster.
    triangle = b.Polygon(
        (0, inner), (half_width, rail_outer + depth), (-half_width, rail_outer + depth), align=None
    )
    north_rail = b.extrude(triangle, amount=rail_height)
    bottom_bevel = p["rail_bottom_chamfer"]
    if bottom_bevel:
        if not captured:
            raise ValueError(
                "Rail underside chamfer currently requires captured-base support collars"
            )
        support_y = math.sqrt(captured["collar_outer_radius"] ** 2 - half_width**2)
        if rail_outer + depth - bottom_bevel > support_y:
            raise ValueError("Increase rail bottom chamfer to reach the supporting collar")
        tip = rail_outer + depth
        cutter_profile = b.Plane.YZ * b.Polygon(
            (tip - bottom_bevel - 0.1, -0.1),
            (tip + 1, -0.1),
            (tip + 1, bottom_bevel + 1),
            align=None,
        )
        cutter = b.Pos(-half_width - 1, 0, 0) * b.extrude(
            cutter_profile, amount=2 * (half_width + 1)
        )
        north_rail = north_rail.cut(cutter)
    south_rail = b.Rot(0, 0, 180) * north_rail
    frame = ring.fuse(north_rail, south_rail)
    if captured:
        from cad.captured_base import channel_void

        frame = frame.cut(channel_void(captured))
    left = frame.intersect(
        box(
            -extent - 1,
            -extent - depth - 1,
            minimum_z,
            extent + 1,
            2 * (extent + depth + 1),
            height - minimum_z + 1,
        )
    )
    right = frame.intersect(
        box(
            0,
            -extent - depth - 1,
            minimum_z,
            extent + 1,
            2 * (extent + depth + 1),
            height - minimum_z + 1,
        )
    )

    # Exact 2D miter offset of the rail's triangular cross-section by clearance.
    slope = half_width / (rail_outer - inner + depth)
    delta = clearance * math.sqrt(1 + slope * slope)
    cavity_back = rail_outer + depth + clearance
    cavity_half_width = slope * (cavity_back - inner) + delta
    cavity_tip = inner - delta / slope
    channel = b.Polygon(
        (0, cavity_tip),
        (cavity_half_width, cavity_back),
        (-cavity_half_width, cavity_back),
        align=None,
    )
    lock_bottom = rail_height - length
    clip = box(
        -cavity_half_width - skin,
        rail_outer + clearance,
        lock_bottom,
        2 * (cavity_half_width + skin),
        depth + skin,
        length + skin,
    ).cut(b.Pos(0, 0, lock_bottom - 0.01) * b.extrude(channel, amount=length + 0.01))
    parts = {
        "wall_left": left,
        "wall_right": right,
        "lock_front": b.Rot(0, 0, 180) * clip,
        "lock_back": clip,
    }
    refs = {}
    base_design = None
    if doc.base_lock:
        from cad.base_lock import modify_parts, references
        from cad.solid_master import dimensions as master_dimensions

        m = master_dimensions(doc, surface)
        base_design = m["base_lock"]
        parts = modify_parts(parts, base_design, m)
        refs = references(base_design)
    for name, shape in parts.items():
        if isinstance(shape, (list, b.ShapeList)):
            shape = b.Compound(children=list(shape))
            parts[name] = shape
        if not shape.is_valid or len(shape.solids()) != 1:
            raise ValueError(f"{name} must be one valid connected solid")
        shape.label = name
        shape.color = b.Color(COLORS.get(name, "#65bdaa"))

    left, right = parts["wall_left"], parts["wall_right"]
    intersections = {}
    for i, (name, shape) in enumerate(parts.items()):
        for other, other_shape in list(parts.items())[i + 1 :]:
            intersections[f"{name}:{other}"] = overlap(shape, other_shape)
    if max(intersections.values()) > 1e-5:
        raise ValueError(f"Tooling parts interfere when assembled: {intersections}")
    # Open floor and mouth, and an unobstructed plaster cavity.
    cavity_probe = (
        b.Pos(0, 0, -0.5)
        * b.Cylinder(inner, height + 1, align=(b.Align.CENTER, b.Align.CENTER, b.Align.MIN))
        if config.profile == "round"
        else box(-inner, -inner, -0.5, 2 * inner, 2 * inner, height + 1)
    )
    cavity_overlap = sum(overlap(part, cavity_probe) for part in parts.values())
    if cavity_overlap > 1e-5:
        raise ValueError("Tooling protrudes into the plaster cavity")
    # Swept clip is a single constant C profile below its closed top cap. The
    # analytic section clearance proves the path; sample poses guard construction.
    sliding_overlap = 0.0
    for name in ("lock_front", "lock_back"):
        for lift in (0, 5, length / 2, length, length + 10):
            raised = b.Pos(0, 0, lift) * parts[name]
            sliding_overlap = max(sliding_overlap, overlap(raised, left), overlap(raised, right))
    if sliding_overlap > 1e-5:
        raise ValueError("A lock interferes with the vertical insertion/removal path")
    # Positive retention check: spreading each half by 2 mm must hit a clip.
    retention = {}
    for name, move in (("wall_left", -2), ("wall_right", 2)):
        spread = b.Pos(move, 0, 0) * parts[name]
        retention[name] = sum(overlap(spread, parts[lock]) for lock in ("lock_front", "lock_back"))
    if min(retention.values()) <= 1e-4:
        raise ValueError(f"The slide clips do not retain both wall halves: {retention}")

    print_parts = {}
    for name, shape in parts.items():
        # Walls stand on their bottom edges. Clips lie on their flat backs,
        # so the dovetail channel opens upward and the top stop is an end wall.
        rotation = (
            (90, 0, 0)
            if name == "lock_front"
            else (-90, 0, 0)
            if name == "lock_back"
            else (0, 0, 0)
        )
        if name.startswith("base_clamp_"):
            from cad.base_lock import ANGLES

            printed = b.Rot(90, 0, 0) * b.Rot(0, 0, -ANGLES[name]) * shape
        else:
            printed = b.Rot(*rotation) * shape
        minimum = printed.bounding_box().min
        printed = b.Pos(-minimum.X, -minimum.Y, -minimum.Z) * printed
        printed.label = name
        print_parts[name] = printed
    dimensions = {
        **p,
        "profile": config.profile,
        **(
            {"inner_diameter": 2 * inner, "outer_diameter": 2 * outer}
            if config.profile == "round"
            else {}
        ),
        "inner_width": 2 * inner,
        "inner_depth": 2 * inner,
        "wall_height": height,
        "wall_only_outer_width": 2 * outer,
        "wall_only_outer_depth": 2 * outer,
        "rail_height": rail_height,
        "lock_bottom_z": lock_bottom,
        "lock_top_z": rail_height + skin,
        "lock_overall_height": length + skin,
        "lock_overall_width": 2 * (cavity_half_width + skin),
        "lock_overall_depth": depth + skin,
        "plaster_envelope_radius": envelope,
        "suggested_clip_removal_lift": length + 10,
    }
    checks = {
        "assembled_pair_overlap_mm3": intersections,
        "plaster_cavity_intrusion_mm3": cavity_overlap,
        "maximum_sampled_slide_overlap_mm3": sliding_overlap,
        "spread_2mm_retention_interference_mm3": retention,
        "normal_dovetail_clearance_mm": clearance,
        "top_stop": "clip cap contacts rail top at zero lift; intentional face contact",
        "rail_bottom_chamfer_mm": p["rail_bottom_chamfer"],
        "rail_bottom_ramp_degrees": 45 if p["rail_bottom_chamfer"] else None,
        "open_top": True,
        "open_bottom": True,
    }
    if doc.solid_master:
        from cad.solid_master import dimensions as master_dimensions

        m = master_dimensions(doc, surface)
        align = (b.Align.CENTER, b.Align.CENTER, b.Align.MIN)
        if captured:
            from cad.captured_base import master_base

            base = master_base(m, captured)
        else:
            base = b.Pos(0, 0, -m["base_thickness"]) * b.Cylinder(
                m["base_radius"], m["base_thickness"], align=align
            )
        lip = b.Cylinder(m["lip_outer_radius"], m["lip_height"], align=align).cut(
            b.Pos(0, 0, -1) * b.Cylinder(m["lip_inner_radius"], m["lip_height"] + 2, align=align)
        )
        base = base.fuse(lip)
        if m["pedestal_base_chamfer"]:
            c = m["pedestal_base_chamfer"]
            radius = m["collar_radius"]
            foot = b.Cone(radius + c, radius, c, align=align).cut(
                b.Pos(0, 0, -1) * b.Cylinder(radius, c + 2, align=align)
            )
            base = base.fuse(foot)
        if m["plaster_corner_chamfer"]:
            c = m["plaster_corner_chamfer"]
            bevel = b.Cylinder(m["lip_outer_radius"], c, align=align).cut(
                b.Cone(m["lip_outer_radius"] - c, m["lip_outer_radius"], c, align=align)
            )
            base = base.fuse(b.Pos(0, 0, m["lip_height"]) * bevel)
        if captured:
            from cad.captured_base import checks as capture_checks

            checks["captured_base"] = capture_checks(parts, base, captured, overlap)
        if base_design:
            groove = b.Pos(0, 0, -base_design["groove_depth"]) * b.Cylinder(
                base_design["groove_outer_radius"], base_design["groove_depth"] + 0.1, align=align
            )
            core = b.Pos(0, 0, -base_design["groove_depth"] - 1) * b.Cylinder(
                base_design["groove_inner_radius"], base_design["groove_depth"] + 2, align=align
            )
            base = base.cut(groove.cut(core))
            from cad.base_lock import checks as lock_checks

            checks["base_lock"] = lock_checks(parts, refs, base, base_design, overlap)
        overlaps = {name: overlap(base, shape) for name, shape in parts.items()}
        withdrawal = {
            f"{name}:{move}mm": overlap(base, b.Pos(move, 0, 0) * parts[name])
            for name, move in (
                ("wall_left", -2),
                ("wall_right", 2),
                ("wall_left", -20),
                ("wall_right", 20),
            )
        }
        if max([*overlaps.values(), *withdrawal.values()]) > 1e-5:
            raise ValueError("Integral base/lip interferes with the formwork or removal")
        checks["integral_base_overlap_mm3"] = overlaps
        checks["base_lip_sampled_wall_withdrawal_overlap_mm3"] = withdrawal
        checks["base_lip_radial_clearance_mm"] = m["lip_clearance"]
        checks["master_collar_to_wall_clearance_mm"] = m["collar_to_wall_clearance"]
        checks["base_seating"] = (
            "wall bottom faces contact the base top at Z=0; locating lip, not a snap lock"
        )
    return Tooling(parts, print_parts, dimensions, checks, refs)


def mesh_data(shape):
    vertices, faces = shape.tessellate(0.05, 0.1)
    return np.array([list(v) for v in vertices]), np.array(faces)


def welded(vertices, faces):
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    mesh.merge_vertices(digits_vertex=8)
    return mesh.vertices, mesh.faces


def artifacts(doc, surface, directory: Path):
    from cad.gentle_twist import export_3mf, validate_mesh

    tooling = build(doc, surface)
    exports, previews, measurements, validations = {}, [], {}, {}
    for name, shape in tooling.parts.items():
        vertices, faces = mesh_data(shape)
        mv, mf = welded(vertices, faces)
        expected_euler = 0 if name.startswith("base_clamp_") else 2
        _, topology = validate_mesh(mv, mf, expected_euler=expected_euler)
        bounds = shape.bounding_box()
        pv, pf = mesh_data(tooling.print_parts[name])
        pv, pf = welded(pv, pf)
        printed_mesh, _ = validate_mesh(pv, pf, expected_euler=expected_euler)
        printed_mesh.export(directory / f"{name}.stl", file_type="stl")
        export_3mf(pv, pf, name, directory / f"{name}.3mf")
        if not b.export_step(shape, directory / f"{name}.step"):
            raise ValueError(f"STEP export failed for {name}")
        # Validate the float32 mesh as reloaded from each printing file.
        stl = trimesh.load(directory / f"{name}.stl", force="mesh", process=False)
        stl.merge_vertices(digits_vertex=8)
        _, stl_report = validate_mesh(stl.vertices, stl.faces, expected_euler=expected_euler)
        wrapper = lib3mf.get_wrapper()
        model = wrapper.CreateModel()
        model.QueryReader("3mf").ReadFromFile(str(directory / f"{name}.3mf"))
        objects = model.GetMeshObjects()
        objects.MoveNext()
        obj = objects.GetCurrentMeshObject()
        v3 = np.array([list(obj.GetVertex(i).Coordinates) for i in range(obj.GetVertexCount())])
        f3 = np.array([list(obj.GetTriangle(i).Indices) for i in range(obj.GetTriangleCount())])
        _, mf_report = validate_mesh(v3, f3, expected_euler=expected_euler)
        validations[name] = {"assembled": topology, "stl": stl_report, "3mf": mf_report}
        measurements[name] = {
            "bounds": {"min": list(bounds.min), "max": list(bounds.max)},
            "x": bounds.size.X,
            "y": bounds.size.Y,
            "z": bounds.size.Z,
            "volume": shape.volume,
            "area": shape.area,
            "solid_count": 1,
            "valid": True,
            "color": COLORS.get(name, "#65bdaa"),
            "export_triangles": len(pf),
            "role": "base screw clamp — add purchased M5 bolt and nut"
            if name.startswith("base_clamp_")
            else (
                "outer casting-box wall" if name.startswith("wall") else "slide-down locking clip"
            ),
            "print_dimensions": list(tooling.print_parts[name].bounding_box().size),
        }
        edges = []
        for edge in shape.edges():
            count = (
                2
                if edge.geom_type == b.GeomType.LINE
                else min(512, max(32, math.ceil(edge.length / 0.8)))
            )
            samples = [list(edge.position_at(i / (count - 1))) for i in range(count)]
            for first, second in zip(samples, samples[1:]):
                edges.extend((first, second))
        offset = (
            [-40, 0, 0]
            if name == "wall_left"
            else [40, 0, 0]
            if name == "wall_right"
            else [0, 0, 100]
        )
        if name.startswith("base_clamp_"):
            from cad.base_lock import ANGLES

            angle = math.radians(ANGLES[name])
            offset = [45 * math.cos(angle), 45 * math.sin(angle), 0]
        # OCCT tessellation has separate vertices per face, keeping rim/key
        # creases sharp. Give only the cylindrical faces exact radial normals.
        extra = {}
        if doc.casting_box.profile == "round" and name.startswith("wall"):
            display_mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
            normals = display_mesh.vertex_normals.copy()
            radii = np.linalg.norm(vertices[:, :2], axis=1)
            vertical = np.abs(display_mesh.face_normals[:, 2]) < 1e-8
            for radius, sign in (
                (tooling.dimensions["inner_diameter"] / 2, -1),
                (tooling.dimensions["outer_diameter"] / 2, 1),
            ):
                selected = vertical & np.all(np.abs(radii[faces] - radius) < 1e-6, axis=1)
                indices = np.unique(faces[selected])
                normals[indices, :2] = sign * vertices[indices, :2] / radii[indices, None]
                normals[indices, 2] = 0
            extra["normals"] = normals.tolist()
        previews.append(
            {
                **extra,
                "name": name,
                "color": COLORS.get(name, "#65bdaa"),
                "vertices": vertices.tolist(),
                "triangles": faces.tolist(),
                "edges": edges,
                "opacity": 0.3 if name.startswith("wall") else 1,
                "exploded_offset": offset,
            }
        )
        for fmt in ("stl", "3mf", "step"):
            exports[f"{fmt}:{name}"] = f"{name}.{fmt}"
    for name, shape in tooling.references.items():
        color = "#344e40" if name == "base_gasket" else "#b8bec6"
        role = (
            "PURCHASED silicone seal — compressed visualization, not a print part"
            if name == "base_gasket"
            else "PURCHASED M5 bolt + nut — schematic, threads not modeled"
        )
        shape.label = name
        shape.color = b.Color(color)
        if name == "base_gasket":
            from cad.base_lock import gasket_mesh

            vertices, faces = gasket_mesh(tooling.checks["base_lock"]["dimensions"])
        else:
            vertices, faces = mesh_data(shape)
        mv, mf = welded(vertices, faces)
        _, topology = validate_mesh(mv, mf, expected_euler=0 if name == "base_gasket" else 2)
        validations[name] = {"reference_only": topology}
        bounds = shape.bounding_box()
        measurements[name] = {
            "bounds": {"min": list(bounds.min), "max": list(bounds.max)},
            "x": bounds.size.X,
            "y": bounds.size.Y,
            "z": bounds.size.Z,
            "volume": shape.volume,
            "area": shape.area,
            "solid_count": 1,
            "valid": shape.is_valid,
            "color": color,
            "role": role,
            "export_triangles": 0,
        }
        if name == "base_gasket":
            offset = [0, 0, 8]
        else:
            from cad.base_lock import ANGLES

            angle = math.radians(ANGLES["base_clamp_" + name.removeprefix("m5_")])
            offset = [45 * math.cos(angle), 45 * math.sin(angle), 0]
        normal_mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
        previews.append(
            {
                "name": name,
                "color": color,
                "vertices": vertices.tolist(),
                "triangles": faces.tolist(),
                "normals": normal_mesh.vertex_normals.tolist(),
                "edges": [],
                "exploded_offset": offset,
            }
        )
    # STEP is tooling plus purchased-component references, NEVER a faceted master.
    assembly = b.Compound(
        label="B-01 casting box tooling",
        children=[*tooling.parts.values(), *tooling.references.values()],
    )
    if not b.export_step(assembly, directory / "casting-box.step"):
        raise ValueError("Tooling assembly STEP export failed")
    exports["step:casting_box"] = "casting-box.step"
    report = {
        "dimensions": tooling.dimensions,
        "assembly_checks": tooling.checks,
        "part_validation": validations,
        "scope": "outer formwork only; reference dripper is not a filled mold master",
        "print_orientation": "Separate STL/3MF: wall bases at Z=0; clips flat-back-down, each part at positive XYZ. STEP retains assembled positions.",
        "use_notes": [
            "Assemble on a flat sealed casting board; no bottom plate is included.",
            "Slide both clips down from above until their caps seat on the rail tops.",
            "Seal the split seams/base and use a compatible release agent; this is not a liquid-tight or pressure-rated enclosure.",
            "Withdraw clips upward before removing the two formwork halves sideways.",
            "Test-print a clip and rail fit before printing the complete formwork.",
            "An exterior positive master, staged plaster pour/parting plan, mold registration and undercut/release assessment are still required.",
            "No clay shrinkage compensation has been applied; slip-cast wall thickness and firing shrinkage require process calibration.",
        ],
    }
    if doc.solid_master:
        report["scope"] = (
            "outer formwork with one-piece master, collar and lipped base; no plaster parting surfaces or shrinkage compensation"
        )
        report["print_orientation"] = (
            "Master STL/3MF: base-down at Z=0, centered XY. Hardware STL/3MF: separately normalized positive XYZ. STEP contains hardware ONLY in assembled positions; no STEP master is claimed."
        )
        report["use_notes"] = [
            "model.stl/model.3mf contain ONE filled master with integral round base, locating lip and top collar; print base-down at Z=0.",
            "Seat both wall halves on the base around its locating lip, then slide the clips down.",
            "The lip locates the halves; it is not a snap joint or guaranteed seal. Seal the wall seams/base and test the sliding fits.",
            "Remove both clips and withdraw walls sideways before lifting plaster from the master/base.",
            "A staged plaster pour, parting surfaces and undercut/release assessment remain necessary: twisted flutes and the wider top collar prevent assuming simple axial demolding.",
            "No clay shrinkage compensation has been applied. This is not a production-ready mold or pressure-rated assembly.",
        ]
        if doc.solid_master.wide_end_down:
            from cad.solid_master import dimensions as master_dimensions

            m = master_dimensions(doc, surface)
            report["use_notes"] = [
                "One-piece master is WIDE END DOWN: base at Z=-4..0 for the default dimensions; collar pedestal is below the inverted flutes.",
                "Print the master base-down. Seat the two wall halves around the locating lip and slide down the locks. Seal the seams and lip fit before pouring.",
                "Remove the locks and wall halves first, then lift the plaster upward (+Z) off the fixed master/base.",
                f"Analytic radial-draw check: no axial undercut = {m['axial_draw_no_undercut']}; minimum flute radial taper = {m['minimum_flute_radial_taper']:.6f} mm/mm.",
                "The collar and locating lip are straight-sided: use a compatible release agent and test release. Geometric draw clearance is not a friction, strength or manufacturing guarantee.",
                "No firing shrinkage compensation is included; plaster mold design and process calibration remain separate.",
            ]
    if doc.captured_base:
        report["captured_base"] = tooling.checks["captured_base"]
        report["use_notes"] = tooling.checks["captured_base"]["assembly"]
        report["print_orientation"] += (
            " Captured-base version: all five components are printed. Wall halves stand on their bottom collars. No purchased components. Check the joint notes for flat-shoulder overhang support requirements. Separate print STLs do not retain assembly placement; the floor underside sits 4 mm above the walls' bottom edges when assembled."
        )
    if doc.base_lock:
        report["base_lock"] = tooling.checks["base_lock"]
        report["print_orientation"] += (
            " Print C-clamps on their supplied flat-side orientation; clear/drill M5 bores as needed. Purchased bolts/nuts/gasket appear only as reference geometry, not STL/3MF print parts."
        )
        report["use_notes"] = tooling.checks["base_lock"]["assembly"] + [
            "The enlarged 6 mm base has a continuous 2.8 mm wide × 1.5 mm deep seal groove; use a 2 mm silicone ring (25% nominal compression).",
            "The master, fluted body, collar, lipped/grooved base remain one solid. The four clamp bodies are separate printed parts; screws and nuts must be purchased.",
            "STEP excludes the master and includes schematic purchased hardware. This geometry is not load-rated or leak-certified.",
        ]
    if tooling.dimensions["rail_bottom_chamfer"]:
        report["use_notes"].append(
            f"Triangular side rails have {tooling.dimensions['rail_bottom_chamfer']:g} mm, 45-degree underside ramps landing within the support collar; retain the supplied wall print orientation."
        )
    if doc.solid_master:
        from cad.solid_master import dimensions as master_dimensions

        tip = master_dimensions(doc, surface)
        if tip["pedestal_base_chamfer"]:
            report["use_notes"].append(
                f"The floor-to-central-pedestal junction has a continuous {tip['pedestal_base_chamfer']:g} mm x 45-degree chamfer, integral with the master. It is separate from the outer plaster-corner former."
            )
        if tip["tip_extension"]:
            report["use_notes"].append(
                f"Narrow-end extension: {tip['tip_extension']:g} mm total, with {tip['tip_transition']:g} mm smooth blend then {tip['tip_straight_length']:g} mm straight circular neck, diameter {2 * tip['tip_radius']:g} mm. Remaining plaster space above tip: {tip['plaster_cover_above_master']:g} mm."
            )
    if surface.profile == "origami":
        report["use_notes"].append(
            f"Origami-style master: {surface.flute_count} ridges alternating with {surface.flute_count} valleys, {2 * surface.flute_count} planar panels, zero twist. Lower and upper fold amplitudes scale with their mean radii. This is a filled casting master, not a hollow finished dripper."
        )
    (directory / "casting-box-report.json").write_text(json.dumps(report, indent=2))
    with zipfile.ZipFile(directory / "casting-box.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for filename in exports.values():
            archive.write(directory / filename, filename)
        if doc.solid_master:
            for filename in ("model.stl", "model.3mf"):
                archive.write(directory / filename, filename)
        if doc.captured_base:
            from cad.captured_base import section_svg

            archive.writestr(
                "joint-section.svg", section_svg(m, tooling.checks["captured_base"]["dimensions"])
            )
        archive.write(directory / "casting-box-report.json", "casting-box-report.json")
        archive.writestr("parametric-source.json", doc.model_dump_json(indent=2))
        archive.writestr(
            "READ-ME.txt",
            (
                "ONE-PIECE MASTER + OUTER FORMWORK — not a finished plaster mold.\n\n"
                if doc.solid_master
                else "OUTER CASTING BOX ONLY — not a plaster mold or master.\n\n"
            )
            + report["print_orientation"]
            + "\n\n"
            + "\n".join(report["use_notes"]),
        )
    exports = {"zip:casting_box": "casting-box.zip", **exports}
    return {"previews": previews, "parts": measurements, "exports": exports, "report": report}
