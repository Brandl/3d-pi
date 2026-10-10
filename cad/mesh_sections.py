"""Explicit, approximate sections of immutable assembly preview meshes.

Never infer a plane from print-oriented STL exports and never silently fall back
from STEP. This is not reconstruction of an analytic surface or exact B-rep.
"""

import json
from pathlib import Path

import numpy as np

from cad.sections import MAX_POINTS, VERSION, draw_section, frame


def signed_area(loop):
    return float(np.sum(loop[:-1, 0] * loop[1:, 1] - loop[1:, 0] * loop[:-1, 1]) / 2)


def make_mesh_section(preview: Path, measurements, request, destination: Path, revision):
    import ezdxf
    import trimesh
    from matplotlib.path import Path as PolygonPath

    if preview.stat().st_size > 64 * 1024**2:
        raise ValueError("Assembly mesh exceeds 64 MiB section input limit")
    data = json.loads(preview.read_text())
    parts = data.get("parts", [])
    names = [p["name"] for p in parts]
    if (
        data.get("units") != "mm"
        or len(names) != len(set(names))
        or set(names) != set(measurements)
    ):
        raise ValueError("Assembly mesh units/part identity do not match revision metadata")
    if set(request.parts or []) - set(names):
        raise ValueError("Unknown output parts; use cad_tree")
    axes = frame(request)
    origin = np.array(axes["origin"])
    basis = np.array([axes["u"], axes["v"]])
    regions, summaries = [], []
    count = triangles = 0
    dxf = ezdxf.new("R2010")
    dxf.units = ezdxf.units.MM
    for part in parts:
        name = part["name"]
        if request.parts is not None and name not in request.parts:
            continue
        triangles += len(part["triangles"])
        if triangles > 500000:
            raise ValueError("Selected assembly meshes exceed 500,000 triangles")
        # Welding duplicate tessellation vertices is allowed; no hole filling,
        # winding repair, reconstruction or resampling of the immutable surface.
        mesh = trimesh.Trimesh(part["vertices"], part["triangles"], process=True)
        if not np.isfinite(mesh.vertices).all() or not mesh.is_volume:
            raise ValueError(
                f"{name}: section requires a closed, consistently oriented volume mesh"
            )
        target = measurements[name]["bounds"]
        if not np.allclose(mesh.bounds, [target["min"], target["max"]], atol=1, rtol=0):
            raise ValueError(f"{name}: mesh is not in the recorded assembly/world frame")
        section = mesh.section(plane_origin=origin, plane_normal=axes["normal"])
        loops = []
        if section is not None:
            for path in section.discrete:
                if len(path) < 4 or np.linalg.norm(path[0] - path[-1]) > 1e-7:
                    raise ValueError(
                        "Section has an open/degenerate contour; choose a nearby plane"
                    )
                loop = (path - origin) @ basis.T
                loop[-1] = loop[0]
                count += len(loop)
                if count > MAX_POINTS or len(loops) >= 2000:
                    raise ValueError("Mesh section exceeds contour/point limit")
                if abs(signed_area(loop)) > 1e-9:
                    loops.append(loop)
        # Closed volume sections have disjoint or nested loops. Classify nesting
        # by parity, retaining holes and islands rather than filling everything.
        paths = [PolygonPath(loop) for loop in loops]
        areas = [abs(signed_area(loop)) for loop in loops]
        parents = []
        for i, loop in enumerate(loops):
            containers = [
                j for j, p in enumerate(paths) if areas[j] > areas[i] and p.contains_point(loop[0])
            ]
            parents.append(min(containers, key=lambda j: areas[j]) if containers else None)
        depths = []
        for parent in parents:
            depth = 0
            while parent is not None:
                depth += 1
                parent = parents[parent]
            depths.append(depth)
        layer = f"part_{len(summaries) + 1}"
        dxf.layers.new(layer)
        part_regions = []
        for i, loop in enumerate(loops):
            clockwise = bool(depths[i] % 2)
            if (signed_area(loop) < 0) != clockwise:
                loops[i] = loop[::-1]
            dxf.modelspace().add_lwpolyline(
                loops[i][:-1].tolist(), close=True, dxfattribs={"layer": layer}
            )
        for i, loop in enumerate(loops):
            if depths[i] % 2:
                continue
            holes = [loops[j].tolist() for j, parent in enumerate(parents) if parent == i]
            part_regions.append({"part": name, "outer": loop.tolist(), "holes": holes})
        regions.extend(part_regions)
        summaries.append(
            {
                "name": name,
                "area_mm2": sum((-1 if depths[i] % 2 else 1) * a for i, a in enumerate(areas)),
                "perimeter_mm": sum(
                    float(np.linalg.norm(np.diff(loop, axis=0), axis=1).sum()) for loop in loops
                ),
                "regions": len(part_regions),
                "holes": sum(len(r["holes"]) for r in part_regions),
                "dxf_layer": layer,
            }
        )
    destination.mkdir(parents=True, exist_ok=True)
    dxf.saveas(destination / "section.dxf")
    summary = {
        "revision": revision,
        "module_version": VERSION,
        "parameters": request.model_dump(mode="json"),
        "plane": axes,
        "representation": "mesh",
        "basis": "Approximate immutable assembly-mesh intersection; polygonal DXF and mesh-derived areas/perimeters, NOT exact analytic/STEP geometry",
        "units": "mm",
        "parts": summaries,
        "empty": not regions,
        "area_sum_mm2": sum(p["area_mm2"] for p in summaries),
        "sampled_points": count,
        "notes": [
            "Explicit mesh mode. Source tessellation error is not a certified global bound.",
            "Assembly/world coordinates, not print-oriented STL coordinates.",
            "Deflection does not refine source meshes. All formats retain the intersected polygon segments.",
            "Parts remain independent; overlaps are not unioned. Coplanar/tangent sections may be degenerate.",
            "Not a fit, thickness, strength or manufacturing certificate.",
        ],
    }
    (destination / "section.json").write_text(
        json.dumps({**summary, "regions": regions}, allow_nan=False)
    )
    draw_section(regions, summary, destination)
    (destination / "summary.json").write_text(json.dumps(summary, allow_nan=False))
    return summary
