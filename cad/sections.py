"""Revision-bound full material sections. No document rebuild or design mutation.

The plane origin is offset along the UNTILTED axis. Tilt is intrinsic: rotate
about initial U, then rotated V. U/V/N form a right-handed frame. STEP geometry
and areas are exact-kernel results; PNG/SVG/JSON outlines are sampled curves.
"""

import json
import math
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field

from cad.schema import Strict

Angle = Annotated[float, Field(ge=-180, le=180, allow_inf_nan=False)]


class SectionRequest(Strict):
    representation: Literal["step", "mesh"] = "step"
    axis: Literal["x", "y", "z"] = "z"
    offset: float = Field(default=0, ge=-10000, le=10000, allow_inf_nan=False)
    tilt: tuple[Angle, Angle] = (0, 0)
    parts: list[Annotated[str, Field(min_length=1, max_length=100)]] | None = Field(
        default=None, min_length=1, max_length=32
    )
    deflection: float = Field(default=0.02, ge=0.005, le=0.5, allow_inf_nan=False)


FILES = {"section.png", "section.svg", "section.dxf", "section.json"}
VERSION = 2
MAX_POINTS = 100000


def frame(request):
    import numpy as np

    u, v, n = {
        "x": ([0, 1, 0], [0, 0, 1], [1, 0, 0]),
        "y": ([-1, 0, 0], [0, 0, 1], [0, 1, 0]),
        "z": ([1, 0, 0], [0, 1, 0], [0, 0, 1]),
    }[request.axis]
    u, v, n = (np.array(a, dtype=float) for a in (u, v, n))
    origin = n * request.offset

    def rotate(vector, axis, angle):
        angle = math.radians(angle)
        return (
            vector * math.cos(angle)
            + np.cross(axis, vector) * math.sin(angle)
            + axis * np.dot(axis, vector) * (1 - math.cos(angle))
        )

    v, n = rotate(v, u, request.tilt[0]), rotate(n, u, request.tilt[0])
    u, n = rotate(u, v, request.tilt[1]), rotate(n, v, request.tilt[1])
    return {"origin": origin.tolist(), "u": u.tolist(), "v": v.tolist(), "normal": n.tolist()}


def load_parts(step: Path, measurements):
    """Recover output names even where STEP repeats a shared prototype's label.

    Never guess ambiguous identity. Bounds/volume match revision metadata to
    assembly occurrences, not a claim of geometric equivalence between designs.
    """
    import build123d as b

    assembly = b.import_step(step)
    children = list(assembly.children) or [assembly]
    if len(children) != len(measurements):
        raise ValueError("STEP assembly occurrences do not match revision part metadata")
    result = {}
    remaining = list(children)
    for name, stats in measurements.items():

        def matches(shape):
            bounds = shape.bounding_box()
            target = stats.get("bounds", {})
            if not target or "volume" not in stats:
                return False
            actual = list(bounds.min) + list(bounds.max)
            expected = target["min"] + target["max"]
            return all(abs(a - z) < 1e-4 for a, z in zip(actual, expected)) and math.isclose(
                shape.volume, stats["volume"], rel_tol=1e-7, abs_tol=1e-4
            )

        candidates = [shape for shape in remaining if matches(shape)]
        if len(candidates) > 1:
            candidates = [shape for shape in candidates if shape.label == name]
        if len(candidates) != 1:
            raise ValueError(f"Cannot unambiguously identify STEP occurrence for {name!r}")
        result[name] = candidates[0]
        remaining.remove(candidates[0])
    return result


def make_section(parts, request: SectionRequest, destination: Path, revision: str):
    import build123d as b
    import numpy as np

    unknown = set(request.parts or []) - parts.keys()
    if unknown:
        raise ValueError(f"Unknown output parts: {sorted(unknown)}; use cad_tree")
    selected = {
        name: shape
        for name, shape in parts.items()
        if request.parts is None or name in request.parts
    }
    axes = frame(request)
    plane = b.Plane(origin=axes["origin"], x_dir=axes["u"], z_dir=axes["normal"])
    origin, normal = np.array(axes["origin"]), np.array(axes["normal"])
    regions, summaries = [], []
    exporter = b.ExportDXF(unit=b.Unit.MM)
    points_used = 0
    for index, (name, shape) in enumerate(selected.items()):
        bounds = shape.bounding_box()
        center = np.array(list(bounds.center()))
        # Center the finite cutting face on the part's projection, not the plane
        # origin: far offsets plus near-90-degree tilts still cut an infinite plane.
        center -= normal * np.dot(center - origin, normal)
        cutter = b.Face.make_rect(
            2 * bounds.diagonal + 2,
            2 * bounds.diagonal + 2,
            b.Plane(origin=center.tolist(), x_dir=axes["u"], z_dir=axes["normal"]),
        )
        intersection = shape.intersect(cutter)
        if isinstance(intersection, (list, b.ShapeList)):
            intersection = b.Compound(children=list(intersection))
        faces = [] if intersection is None else [f for f in intersection.faces() if f.area > 1e-9]
        if len(faces) > 2000:
            raise ValueError("Section exceeds face limit")
        local = [plane.to_local_coords(face) for face in faces]
        layer = f"part_{index + 1}"
        exporter.add_layer(layer)
        if local:
            exporter.add_shape(local, layer=layer)
        area = sum(f.area for f in faces)
        perimeter = sum(
            f.outer_wire().length + sum(w.length for w in f.inner_wires()) for f in faces
        )
        summaries.append(
            {
                "name": name,
                "area_mm2": area,
                "perimeter_mm": perimeter,
                "regions": len(faces),
                "holes": sum(len(f.inner_wires()) for f in faces),
                "dxf_layer": layer,
            }
        )
        for face in local:

            def polygon(wire, clockwise):
                nonlocal points_used
                points = [[p.X, p.Y] for p in wire.positions(deflection=request.deflection)]
                if points[0] != points[-1]:
                    points.append(points[0])
                points_used += len(points)
                if points_used > MAX_POINTS:
                    raise ValueError(
                        "Section exceeds sampled point limit; choose fewer parts or larger deflection"
                    )
                signed = sum(a[0] * z[1] - z[0] * a[1] for a, z in zip(points, points[1:]))
                if (signed < 0) != clockwise:
                    points.reverse()
                return points

            regions.append(
                {
                    "part": name,
                    "outer": polygon(face.outer_wire(), False),
                    "holes": [polygon(w, True) for w in face.inner_wires()],
                }
            )
    destination.mkdir(parents=True, exist_ok=True)
    exporter.write(str(destination / "section.dxf"))
    summary = {
        "revision": revision,
        "module_version": VERSION,
        "parameters": request.model_dump(mode="json"),
        "plane": axes,
        "representation": "step",
        "basis": "Exact STEP B-rep intersection; exact kernel areas/perimeters; sampled PNG/SVG/JSON outlines",
        "units": "mm",
        "parts": summaries,
        "empty": not regions,
        "area_sum_mm2": sum(p["area_mm2"] for p in summaries),
        "sampled_points": points_used,
        "notes": [
            "Full material section, not a clipped perspective or projection. Holes remain empty.",
            "Area sum counts each selected part separately; overlapping parts are NOT unioned.",
            "Offset locates the origin on the UNTILTED axis. Tilt degrees: initial U, then rotated V; right-hand rule.",
            "UV coordinates map to world = origin + U*u + V*v. Coplanar faces can appear; zero-area contacts are omitted.",
            "Not a wall-thickness, collision, printability or strength certificate.",
        ],
    }
    (destination / "section.json").write_text(
        json.dumps({**summary, "regions": regions}, allow_nan=False)
    )
    draw_section(regions, summary, destination)
    (destination / "summary.json").write_text(json.dumps(summary, allow_nan=False))
    return summary


def draw_section(regions, summary, destination):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.path import Path as PlotPath
    from matplotlib.patches import Patch, PathPatch

    fig, ax = plt.subplots(figsize=(12, 8), dpi=140)
    names = [p["name"] for p in summary["parts"]]
    colors = {name: plt.get_cmap("tab20")(i % 20) for i, name in enumerate(names)}
    for region in regions:
        vertices, codes = [], []
        for loop in [region["outer"], *region["holes"]]:
            vertices.extend(loop)
            codes.extend(
                [PlotPath.MOVETO] + [PlotPath.LINETO] * (len(loop) - 2) + [PlotPath.CLOSEPOLY]
            )
        ax.add_patch(
            PathPatch(
                PlotPath(vertices, codes),
                facecolor=colors[region["part"]],
                edgecolor="black",
                linewidth=0.7,
                alpha=0.65,
                hatch="///",
            )
        )
    if not regions:
        ax.text(
            0.5,
            0.5,
            "No positive-area material intersects this plane",
            transform=ax.transAxes,
            ha="center",
        )
    ax.autoscale_view()
    ax.margins(0.08)
    ax.set_aspect("equal", adjustable="datalim")
    ax.set_xlabel(f"U (mm) · direction {[round(x, 3) for x in summary['plane']['u']]}")
    ax.set_ylabel(f"V (mm) · direction {[round(x, 3) for x in summary['plane']['v']]}")
    ax.grid(True, alpha=0.2)
    p = summary["parameters"]
    ax.set_title(
        f"Full section · {summary['revision'][:12]}\n{p['axis'].upper()} offset {p['offset']:g} mm · tilt U/V {p['tilt'][0]:g}° / {p['tilt'][1]:g}°"
    )
    if names:
        ax.legend(
            handles=[Patch(facecolor=colors[n], label=n) for n in names],
            loc="upper left",
            bbox_to_anchor=(1.01, 1),
            fontsize=7,
        )
    fig.text(
        0.02,
        0.025,
        (
            "APPROXIMATE MESH section · polygon outlines · not exact analytic geometry"
            if summary.get("representation") == "mesh"
            else "Exact STEP section · hatched material / empty holes · sampled outlines · independent parts (overlap not unioned)"
        ),
        fontsize=8,
    )
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    for suffix in ("png", "svg"):
        fig.savefig(destination / f"section.{suffix}")
    plt.close(fig)


def main():
    import resource
    import sys

    resource.setrlimit(resource.RLIMIT_CPU, (40, 45))
    resource.setrlimit(resource.RLIMIT_AS, (4 * 1024**3, 4 * 1024**3))
    resource.setrlimit(resource.RLIMIT_FSIZE, (16 * 1024**2, 16 * 1024**2))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    destination = Path(sys.argv[1])
    try:
        job = json.loads((destination / "input.json").read_text())
        request = SectionRequest.model_validate(job["parameters"])
        if request.representation == "mesh":
            from cad.mesh_sections import make_mesh_section

            make_mesh_section(
                Path(job["preview"]), job["measurements"], request, destination, job["revision"]
            )
        else:
            parts = load_parts(Path(job["step"]), job["measurements"])
            make_section(parts, request, destination, job["revision"])
    except Exception as exc:
        (destination / "error.json").write_text(json.dumps({"error": str(exc)[:2000]}))
        sys.exit(1)


if __name__ == "__main__":
    main()
