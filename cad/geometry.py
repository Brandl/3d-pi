"""Trusted interpreter for the small declarative modeling language."""

import importlib.metadata
import json
import math
from pathlib import Path

import build123d as b

from cad.schema import Document, Expressions


def construct(doc: Document):
    expressions = Expressions(doc.parameters)
    val = expressions.value

    def length(x):
        n = val(x)
        if not 0.01 <= n <= 2000:
            raise ValueError("Lengths must be between 0.01 and 2000 mm")
        return n

    nodes = {}
    for feature in doc.features:
        try:
            args = [nodes[name] for name in feature.inputs]
            match feature.op:
                case "box":
                    shape = b.Box(
                        *(length(x) for x in feature.size),
                        align=(b.Align.MIN, b.Align.MIN, b.Align.MIN),
                    )
                case "cylinder":
                    shape = b.Cylinder(
                        length(feature.radius),
                        length(feature.height),
                        align=(b.Align.CENTER, b.Align.CENTER, b.Align.MIN),
                    )
                case "extrude":
                    points = [(val(x), val(y)) for x, y in feature.points]
                    if any(abs(v) > 2000 for point in points for v in point):
                        raise ValueError("Profile coordinates must be within +/-2000 mm")
                    shape = b.extrude(b.Polygon(*points, align=None), amount=length(feature.height))
                case "union" | "subtract" | "intersect":
                    shape = args[0]
                    for operand in args[1:]:
                        if feature.op == "union":
                            shape = shape.fuse(operand)
                        elif feature.op == "subtract":
                            shape = shape.cut(operand)
                        else:
                            shape = shape.intersect(operand)
                case "fillet":
                    edges = args[0].edges()
                    if feature.edges != "all":
                        axis = {
                            "parallel_x": b.Axis.X,
                            "parallel_y": b.Axis.Y,
                            "parallel_z": b.Axis.Z,
                        }[feature.edges]
                        edges = edges.filter_by(axis)
                    if not edges:
                        raise ValueError("Edge selector matched no edges")
                    shape = b.fillet(edges, radius=length(feature.radius))
                case "transform":
                    shape = args[0]
            # ShapeList can result from disconnected boolean results. Preserve all solids.
            if isinstance(shape, (list, b.ShapeList)):
                shape = b.Compound(children=list(shape))
            if shape is None or not shape.is_valid or not shape.solids() or shape.volume <= 0:
                raise ValueError("Operation did not produce a valid non-empty solid")
            position = tuple(val(x) for x in feature.position)
            rotation = tuple(val(x) for x in feature.rotation)
            if any(abs(x) > 5000 for x in position) or any(abs(x) > 360 for x in rotation):
                raise ValueError("Placement exceeds limits (+/-5000 mm, +/-360 degrees)")
            shape = b.Pos(*position) * b.Rot(*rotation) * shape
            if max(shape.bounding_box().size) > 10000:
                raise ValueError("Model extent exceeds 10000 mm")
            nodes[feature.name] = shape
        except Exception as exc:
            raise ValueError(f"Feature '{feature.name}' ({feature.op}): {exc}") from exc
    outputs = {}
    for output in doc.outputs:
        shape = nodes[output.feature].moved(b.Location())
        shape.label = output.name
        shape.color = b.Color(output.color)
        outputs[output.name] = shape
    return outputs, expressions


def inspection(parts, doc, expressions):
    measurements = {}
    for name, shape in parts.items():
        box = shape.bounding_box()
        measurements[name] = {
            "bounds": {"min": list(box.min), "max": list(box.max)},
            "x": box.size.X,
            "y": box.size.Y,
            "z": box.size.Z,
            "volume": shape.volume,
            "area": shape.area,
            "solid_count": len(shape.solids()),
            "valid": shape.is_valid,
        }
    checks = []
    for check in doc.checks:
        actual = measurements[check.part][check.metric]
        expected = expressions.value(check.expected)
        checks.append(
            {
                **check.model_dump(),
                "expected": expected,
                "actual": actual,
                "passed": abs(actual - expected) <= check.tolerance,
            }
        )
    return {
        "units": {"length": "mm", "area": "mm²", "volume": "mm³"},
        "parameters": expressions.resolved,
        "parts": measurements,
        "checks": checks,
        "valid": all(p["valid"] for p in measurements.values())
        and all(c["passed"] for c in checks),
    }


def preview(parts, doc):
    result = []
    for output in doc.outputs:
        shape = parts[output.name]
        vertices, triangles = shape.tessellate(doc.linear_tolerance, doc.angular_tolerance)
        if len(triangles) > 300000:
            raise ValueError("Preview triangle limit exceeded")
        edges = []
        for edge in shape.edges():
            count = (
                2
                if edge.geom_type == b.GeomType.LINE
                else min(256, max(16, math.ceil(edge.length / 0.5)))
            )
            points = [list(edge.position_at(i / (count - 1))) for i in range(count)]
            for a, c in zip(points, points[1:]):
                edges.extend([a, c])
        result.append(
            {
                "name": output.name,
                "color": output.color,
                "vertices": [list(v) for v in vertices],
                "triangles": triangles,
                "edges": edges,
            }
        )
    return {"units": "mm", "parts": result}


def render(mesh, destination: Path, views=None, *, review=False):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection
    from matplotlib.patches import Patch

    palette = plt.get_cmap("tab20")
    names = sorted(part["name"] for part in mesh["parts"])
    review_colors = {
        name: palette((i * 2) % 20 + i // 10)
        if len(names) <= 20
        else plt.get_cmap("hsv")(i / len(names))
        for i, name in enumerate(names)
    }
    all_vertices = np.array([v for p in mesh["parts"] for v in p["vertices"]])
    center = (all_vertices.min(axis=0) + all_vertices.max(axis=0)) / 2
    radius = max(float(np.ptp(all_vertices, axis=0).max()) * 0.6, 1)
    for view, elev, azim in views or [("iso", 30, -55), ("top", 90, -90), ("front", 0, -90)]:
        fig = plt.figure(figsize=(8, 6), dpi=120, facecolor="#111b28")
        ax = fig.add_subplot(projection="3d", facecolor="#111b28")
        for part in mesh["parts"]:
            vertices = np.array(part["vertices"])
            polygons = vertices[np.array(part["triangles"])]
            ax.add_collection3d(
                Poly3DCollection(
                    polygons,
                    facecolors=review_colors[part["name"]] if review else part["color"],
                    edgecolor="none",
                    shade=True,
                    alpha=part.get("opacity", 1),
                )
            )
            edges = np.array(part["edges"])
            from mpl_toolkits.mplot3d.art3d import Line3DCollection

            if edges.size:
                ax.add_collection3d(
                    Line3DCollection(edges.reshape(-1, 2, 3), colors="#1e3646", linewidths=0.4)
                )
        ax.set(
            xlim=(center[0] - radius, center[0] + radius),
            ylim=(center[1] - radius, center[1] + radius),
            zlim=(center[2] - radius, center[2] + radius),
        )
        ax.set_box_aspect((1, 1, 1), zoom=1.6 if review else 1)
        ax.set_proj_type("ortho")
        ax.view_init(elev=elev, azim=azim)
        if review:
            # Cap the closer inspection framing using projected vertices so
            # bulky/diagonal assemblies cannot be cropped by the axes viewport.
            from mpl_toolkits.mplot3d import proj3d

            px, py, _ = proj3d.proj_transform(*all_vertices.T, ax.get_proj())
            window = ax.bbox.transformed(ax.transData.inverted())
            factors = []
            for values, lo, hi in ((px, window.x0, window.x1), (py, window.y0, window.y1)):
                if values.min() < -1e-12:
                    factors.append(lo / values.min())
                if values.max() > 1e-12:
                    factors.append(hi / values.max())
            if factors:
                ax.set_box_aspect((1, 1, 1), zoom=1.6 * min(1.0, 0.9 * min(factors)))
        ax.set_axis_off()
        ax.set_title(f"{'REVIEW · ' if review else ''}{view.upper()} · millimeters", color="white")
        if review:
            fig.legend(
                handles=[Patch(facecolor=review_colors[name], label=name) for name in names],
                loc="lower center",
                ncol=min(3, len(names)),
                fontsize=7,
                facecolor="#172535",
                labelcolor="white",
                edgecolor="#34495c",
            )
            fig.text(
                0.02,
                0.96,
                "Preview geometry · transparent parts retained · not a hidden-line drawing",
                color="#b5c6d5",
                fontsize=7,
            )
        prefix = "review" if review else "render"
        fig.savefig(destination / f"{prefix}-{view}.png", bbox_inches="tight")
        plt.close(fig)
    if not review:
        render(mesh, destination, views=views, review=True)


def build_artifacts(doc: Document, directory: Path):
    if doc.features[0].op == "gentle_twist":
        from cad.gentle_twist import build_artifacts as build_surface

        return build_surface(doc, directory)
    parts, expressions = construct(doc)
    report = inspection(parts, doc, expressions)
    mesh = preview(parts, doc)
    (directory / "preview.json").write_text(json.dumps(mesh))
    exports = {}
    assembly = b.Compound(label=doc.name, children=list(parts.values()))
    if not b.export_step(assembly, directory / "model.step"):
        raise ValueError("STEP export failed")
    if not b.export_stl(
        assembly,
        directory / "model.stl",
        tolerance=doc.linear_tolerance,
        angular_tolerance=doc.angular_tolerance,
    ):
        raise ValueError("STL export failed")
    mesher = b.Mesher(unit=b.Unit.MM)
    for name, shape in parts.items():
        mesher.add_shape(
            shape,
            linear_deflection=doc.linear_tolerance,
            angular_deflection=doc.angular_tolerance,
            part_number=name,
        )
    mesher.write(str(directory / "model.3mf"))
    for fmt in ("step", "stl", "3mf"):
        exports[fmt] = f"model.{fmt}"
    for section in doc.sections:
        z = expressions.value(section.z)
        sliced = b.section(parts[section.part], section_by=b.Plane.XY.offset(z))
        if not sliced.edges():
            raise ValueError(f"DXF section '{section.name}' at z={z} does not intersect the part")
        exporter = b.ExportDXF(unit=b.Unit.MM)
        exporter.add_shape(b.Pos(0, 0, -z) * sliced)
        filename = f"section-{section.name}.dxf"
        exporter.write(str(directory / filename))
        exports[f"dxf:{section.name}"] = filename
    render(mesh, directory)
    return {
        "report": report,
        "exports": exports,
        "engine": {
            name: importlib.metadata.version(name)
            for name in ("build123d", "cadquery-ocp-novtk", "ocp-gordon", "lib3mf")
        },
        "tessellation": {
            "linear_mm": doc.linear_tolerance,
            "angular_radians": doc.angular_tolerance,
        },
    }
