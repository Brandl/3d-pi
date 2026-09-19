"""Analytic cosine-fluted cone and true inward parallel surface.

The equations are the source of truth. Meshes are explicit approximations, not lofts
or B-reps; no STEP is claimed for this generator. Angles are radians internally.
"""

import importlib.metadata
import json
from dataclasses import dataclass
from pathlib import Path

import lib3mf
import numpy as np
import trimesh
from scipy.optimize import minimize_scalar

from cad.schema import Document, Expressions


@dataclass(frozen=True)
class Surface:
    height: float
    bottom_radius: float
    top_radius: float
    bottom_amplitude: float
    top_amplitude: float
    flute_count: int
    twist: float
    thickness: float
    profile: str = "cosine"

    @classmethod
    def from_document(cls, doc):
        e = Expressions(doc.parameters)
        s = doc.features[0].surface
        v = e.value
        count = v(s.flute_count)
        if count != int(count) or int(count) % 2 or not 4 <= count <= 20:
            raise ValueError("Flute count must be an even integer from 4 to 20")
        surface = cls(
            v(s.height),
            v(s.bottom_radius),
            v(s.top_radius),
            v(s.bottom_amplitude),
            v(s.top_amplitude),
            int(count),
            np.deg2rad(v(s.twist_degrees)),
            v(s.wall_thickness),
            s.profile,
        )
        if surface.profile == "origami":
            if not doc.solid_master or not doc.solid_master.wide_end_down:
                raise ValueError("Origami profile currently requires a wide-end-down solid master")
            if surface.twist != 0 or not np.isclose(
                surface.bottom_amplitude / surface.bottom_radius,
                surface.top_amplitude / surface.top_radius,
                atol=1e-12,
                rtol=0,
            ):
                raise ValueError(
                    "Origami requires zero twist and proportional end amplitudes for planar facets"
                )
        if not (
            20 <= surface.height <= 300 and 10 <= surface.bottom_radius < surface.top_radius <= 200
        ):
            raise ValueError(
                "Supported dimensions: height 20..300, radii 10 <= bottom < top <= 200 mm"
            )
        if not (
            0 <= surface.bottom_amplitude <= surface.top_amplitude <= 5
            and 0.1 <= surface.thickness <= 4
            and abs(surface.twist) <= np.pi / 2
        ):
            raise ValueError(
                "Supported amplitudes: 0 <= bottom <= top <= 5; thickness 0.1..4 mm; twist +/-90 degrees"
            )
        if s.angular_samples % (2 * surface.flute_count):
            raise ValueError("Angular samples must be divisible by twice the flute count")
        if 4 * s.angular_samples * (s.vertical_intervals + 1) > 300000:
            raise ValueError("Mesh exceeds 300,000 triangles")
        return surface, e

    def origami_radial(self, theta, u):
        """Ray/chord intersection of alternating ridge/valley vertices, not a polar triangle wave."""
        theta, u = np.broadcast_arrays(theta, u)
        step = np.pi / self.flute_count
        sector = np.floor(theta / step)
        local = theta - sector * step
        sign = np.where(np.remainder(sector, 2) == 0, 1.0, -1.0)
        scale = 1 + (self.top_radius / self.bottom_radius - 1) * u / self.height
        ra = self.bottom_radius + sign * self.bottom_amplitude
        rb = self.bottom_radius - sign * self.bottom_amplitude
        den = rb * np.sin(step - local) + ra * np.sin(local)
        derivative = -rb * np.cos(step - local) + ra * np.cos(local)
        r0 = ra * rb * np.sin(step) / den
        rp0 = -r0 * derivative / den
        rate = (self.top_radius / self.bottom_radius - 1) / self.height
        return r0 * scale, rp0 * scale, r0 * rate, rp0 * rate

    def exterior(self, theta, u):
        """P and analytic outward unit normal, including the specified extension."""
        theta, u = np.broadcast_arrays(theta, u)
        t = u / self.height
        mean = self.bottom_radius + (self.top_radius - self.bottom_radius) * t
        amplitude = self.bottom_amplitude + (self.top_amplitude - self.bottom_amplitude) * t
        phase = self.flute_count * (theta - self.twist * t)
        r = mean + amplitude * np.cos(phase)
        r_theta = -self.flute_count * amplitude * np.sin(phase)
        r_u = (
            (self.top_radius - self.bottom_radius) / self.height
            + (self.top_amplitude - self.bottom_amplitude) / self.height * np.cos(phase)
            + amplitude * self.flute_count * self.twist / self.height * np.sin(phase)
        )
        if self.profile == "origami":
            r, r_theta, r_u, _ = self.origami_radial(theta, u)
        c, s = np.cos(theta), np.sin(theta)
        p = np.stack((r * c, r * s, u), axis=-1)
        normal = np.stack((r * c + r_theta * s, r * s - r_theta * c, -r * r_u), axis=-1)
        normal /= np.linalg.norm(normal, axis=-1, keepdims=True)
        return p, normal

    def offset(self, theta, u):
        if self.profile == "origami":
            raise ValueError(
                "Sharp origami folds are supported only as a filled master, not a normal-offset shell"
            )
        p, normal = self.exterior(theta, u)
        return p - self.thickness * normal, normal

    def inner_ring(self, theta, spatial_z):
        """Solve Q_z(theta,u)=spatial_z; source theta is NOT the final polar angle."""
        theta, spatial_z = np.broadcast_arrays(theta, spatial_z)
        lo = np.full(theta.shape, -5.0)
        hi = np.full(theta.shape, self.height + 5.0)
        if np.any(self.offset(theta, lo)[0][..., 2] > spatial_z) or np.any(
            self.offset(theta, hi)[0][..., 2] < spatial_z
        ):
            raise ValueError("The required offset branch is not bracketed by the -5..H+5 extension")
        for _ in range(46):
            mid = (lo + hi) / 2
            below = self.offset(theta, mid)[0][..., 2] < spatial_z
            lo = np.where(below, mid, lo)
            hi = np.where(below, hi, mid)
        u = (lo + hi) / 2
        q, normal = self.offset(theta, u)
        error = np.max(np.abs(q[..., 2] - spatial_z))
        if error > 1e-8:
            raise ValueError("Interior plane intersection failed to converge")
        q[..., 2] = spatial_z  # Remove only root-solver roundoff, not a geometric displacement.
        return q, -normal, u

    def opening_diameters(self, z):
        # Optimize on the CONTINUOUS offset curve, not just the printing vertices.
        period = 2 * np.pi / self.flute_count
        theta = np.linspace(0, period, 721, endpoint=False)
        radii = np.linalg.norm(self.inner_ring(theta, z)[0][:, :2], axis=1)
        result = []
        for sign, index in [(1, np.argmin(radii)), (-1, np.argmax(radii))]:
            center = theta[index]
            step = period / len(theta)

            def objective(angle):
                return sign * np.linalg.norm(self.inner_ring(angle, z)[0][:2])

            opt = minimize_scalar(
                objective,
                bounds=(center - step, center + step),
                method="bounded",
                options={"xatol": 1e-12},
            )
            result.append(float(2 * sign * opt.fun))
        return {"minimum": result[0], "maximum": result[1]}


def sample_mesh(surface, angular_samples, vertical_intervals):
    a, v = angular_samples, vertical_intervals
    theta = np.broadcast_to(np.arange(a)[None, :] * (2 * np.pi / a), (v + 1, a))
    z = np.broadcast_to(np.linspace(0, surface.height, v + 1)[:, None], theta.shape)
    outer, outer_normals = surface.exterior(theta, z)
    inner, inner_normals, source_u = surface.inner_ring(theta, z)
    stride = (v + 1) * a
    vertices = np.concatenate((outer.reshape(-1, 3), inner.reshape(-1, 3)))
    normals = np.concatenate((outer_normals.reshape(-1, 3), inner_normals.reshape(-1, 3)))
    j, i = np.meshgrid(np.arange(v), np.arange(a), indexing="ij")
    bottom = (j * a + i).ravel()
    next_bottom = (j * a + (i + 1) % a).ravel()
    upper = bottom + a
    next_upper = next_bottom + a
    outside = np.stack(
        (
            np.stack((bottom, next_bottom, upper), axis=1),
            np.stack((next_bottom, next_upper, upper), axis=1),
        ),
        axis=1,
    ).reshape(-1, 3)
    inside = outside[:, [0, 2, 1]] + stride
    i = np.arange(a)
    nxt = (i + 1) % a
    bottom_rim = np.stack(
        (np.stack((i, i + stride, nxt), axis=1), np.stack((nxt, i + stride, nxt + stride), axis=1)),
        axis=1,
    ).reshape(-1, 3)
    top_rim = bottom_rim[:, [0, 2, 1]] + v * a
    faces = np.concatenate((outside, inside, bottom_rim, top_rim))
    return vertices, faces, normals, source_u


def validate_mesh(vertices, faces, expected_euler=0):
    """Never repair silently: reject bad topology, winding, or intersections."""
    import pymeshlab

    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    _, counts = np.unique(np.sort(mesh.edges, axis=1), axis=0, return_counts=True)
    if not np.all(np.isfinite(vertices)):
        raise ValueError("Non-finite vertices")
    edges = np.unique(np.sort(mesh.edges, axis=1), axis=0)
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components

    graph = coo_matrix(
        (np.ones(len(edges)), (edges[:, 0], edges[:, 1])), shape=(len(vertices), len(vertices))
    )
    components = connected_components(graph, directed=False, return_labels=False)
    ms = pymeshlab.MeshSet()
    ms.add_mesh(pymeshlab.Mesh(vertex_matrix=vertices, face_matrix=faces.astype(np.int32)))
    ms.compute_selection_by_self_intersections_per_face()
    intersecting = int(np.count_nonzero(ms.current_mesh().face_selection_array()))
    report = {
        "vertices": len(vertices),
        "triangles": len(faces),
        "open_edges": int(np.count_nonzero(counts == 1)),
        "non_manifold_edges": int(np.count_nonzero(counts > 2)),
        "degenerate_triangles": int(np.count_nonzero(mesh.area_faces < 1e-12)),
        "consistent_winding": bool(mesh.is_winding_consistent),
        "positive_signed_volume": bool(mesh.volume > 0),
        "connected_components": int(components),
        "euler_characteristic": int(mesh.euler_number),
        "self_intersecting_faces": intersecting,
        "self_intersection_method": "MeshLab triangle/triangle self-intersection selection",
    }
    if (
        not mesh.is_watertight
        or not mesh.is_winding_consistent
        or mesh.volume <= 0
        or components != 1
        or mesh.euler_number != expected_euler
        or intersecting
        or report["degenerate_triangles"]
    ):
        raise ValueError(f"Invalid closed mesh: {report}")
    return mesh, report


def analytic_checks(surface, vertices, faces, source_u, angular_samples, vertical_intervals):
    a, v = angular_samples, vertical_intervals
    theta = np.broadcast_to(np.arange(a)[None, :] * (2 * np.pi / a), source_u.shape)
    p, n = surface.exterior(theta, source_u)
    inner = vertices[len(vertices) // 2 :].reshape(source_u.shape + (3,))
    offset = p - inner
    thickness_error = float(np.max(np.abs(np.linalg.norm(offset, axis=-1) - surface.thickness)))
    normal_error = float(np.max(np.linalg.norm(offset - surface.thickness * n, axis=-1)))
    # Check local regularity of the parallel surface and monotonic spatial Z.
    h = 1e-4
    q_theta = (surface.offset(theta + h, source_u)[0] - surface.offset(theta - h, source_u)[0]) / (
        2 * h
    )
    q_u = (surface.offset(theta, source_u + h)[0] - surface.offset(theta, source_u - h)[0]) / (
        2 * h
    )
    jacobian = np.einsum("...i,...i->...", np.cross(q_theta, q_u), n)
    q_angle = np.arctan2(inner[..., 1], inner[..., 0])
    outer_at_q, _ = surface.exterior(q_angle, inner[..., 2])
    radial_gap = np.linalg.norm(outer_at_q[..., :2], axis=-1) - np.linalg.norm(
        inner[..., :2], axis=-1
    )
    if (
        thickness_error > 1e-8
        or normal_error > 1e-8
        or np.min(jacobian) <= 0
        or np.min(q_u[..., 2]) <= 0
        or np.min(radial_gap) <= 0
    ):
        raise ValueError("Normal offset folded, escaped the exterior, or violated thickness")
    # Every surface triangle is checked at its parameter centroid. This is a sampled
    # approximation estimate, NOT a certified global Hausdorff error bound.
    errors = []
    side_count = 2 * a * v
    for side in range(2):
        selected = faces[side * side_count : (side + 1) * side_count]
        indices = selected % ((v + 1) * a)
        angles = (indices % a) * (2 * np.pi / a)
        seam = np.ptp(angles, axis=1) > np.pi
        angles[seam] = np.where(angles[seam] < np.pi, angles[seam] + 2 * np.pi, angles[seam])
        angle = angles.mean(axis=1)
        z = (indices // a).mean(axis=1) * surface.height / v
        reference = surface.exterior(angle, z)[0] if side == 0 else surface.inner_ring(angle, z)[0]
        error = np.linalg.norm(vertices[selected].mean(axis=1) - reference, axis=1)
        errors.append(float(error.max()))
    checkpoints = []
    for t in (0, 0.25, 0.5, 0.75, 1):
        mean = surface.bottom_radius + (surface.top_radius - surface.bottom_radius) * t
        amp = surface.bottom_amplitude + (surface.top_amplitude - surface.bottom_amplitude) * t
        checkpoints.append(
            {
                "z": surface.height * t,
                "mean_radius": mean,
                "amplitude": amp,
                "crest_radius": mean + amp,
                "valley_radius": mean - amp,
                "first_crest_degrees": float(np.rad2deg(surface.twist * t)),
            }
        )
    # Rotation by one flute must map each ring to itself, with no duplicated seam vertex.
    rings = vertices.reshape(2, v + 1, a, 3)
    angle = 2 * np.pi / surface.flute_count
    rot = np.array(
        [[np.cos(angle), -np.sin(angle), 0], [np.sin(angle), np.cos(angle), 0], [0, 0, 1]]
    )
    symmetry_error = float(
        np.max(
            np.linalg.norm(
                rings @ rot.T - np.roll(rings, -a // surface.flute_count, axis=2), axis=-1
            )
        )
    )
    return {
        "normal_thickness_mm": surface.thickness,
        "maximum_normal_thickness_error_mm": thickness_error,
        "maximum_offset_vector_error_mm": normal_error,
        "minimum_offset_jacobian": float(jacobian.min()),
        "minimum_spatial_z_derivative": float(q_u[..., 2].min()),
        "minimum_inner_to_outer_radial_gap_mm": float(radial_gap.min()),
        "symmetry_error_mm": symmetry_error,
        "exterior_checkpoints": checkpoints,
        "bottom_internal_diameters_mm": surface.opening_diameters(0),
        "top_internal_diameters_mm": surface.opening_diameters(surface.height),
        "sampled_triangle_centroid_error_mm": {"exterior": errors[0], "interior": errors[1]},
        "mean_cone_included_angle_degrees": float(
            np.rad2deg(2 * np.arctan((surface.top_radius - surface.bottom_radius) / surface.height))
        ),
        "inner_source_u_range_mm": [float(source_u.min()), float(source_u.max())],
    }


def export_3mf(vertices, faces, name, path):
    wrapper = lib3mf.get_wrapper()
    model = wrapper.CreateModel()
    model.SetUnit(lib3mf.ModelUnit.MilliMeter)
    obj = model.AddMeshObject()
    obj.SetName(name)
    positions = [lib3mf.Position(tuple(v)) for v in vertices]
    triangles = [lib3mf.Triangle(tuple(map(int, f))) for f in faces]
    obj.SetGeometry(positions, triangles)
    if not obj.IsManifoldAndOriented():
        raise ValueError("lib3mf rejected mesh topology/orientation")
    model.AddBuildItem(obj, wrapper.GetIdentityTransform())
    model.QueryWriter("3mf").WriteToFile(str(path))


def build_artifacts(doc: Document, directory: Path):
    from cad.geometry import render

    surface, expressions = Surface.from_document(doc)
    config = doc.features[0].surface
    a, v = config.angular_samples, config.vertical_intervals
    master = None
    if doc.solid_master:
        from cad.solid_master import dimensions, sample

        master = dimensions(doc, surface)
        vertices, faces, normals, _, _ = sample(surface, master, a, v)
        analytic = {
            "kind": "wide-end-down filled master with integral base/lip and collar pedestal"
            if master["wide_end_down"]
            else "filled exterior master with integral base/lip and top collar",
            "dimensions": master,
            "profile": surface.profile,
            "fold_count": surface.flute_count if surface.profile == "origami" else None,
            "planar_panel_count": 2 * surface.flute_count if surface.profile == "origami" else None,
            "flute_exterior_unchanged": True,
            "shrinkage_compensation": False,
            "print_z_translation": master["base_thickness"],
        }
    else:
        vertices, faces, normals, source_u = sample_mesh(surface, a, v)
        analytic = analytic_checks(surface, vertices, faces, source_u, a, v)
    expected_euler = 2 if master else 0
    mesh, topology = validate_mesh(vertices, faces, expected_euler=expected_euler)
    output = doc.outputs[0]
    print_mesh = mesh.copy()
    if master:
        print_mesh.apply_translation([0, 0, master["base_thickness"]])
    print_mesh.export(directory / "model.stl", file_type="stl")
    export_3mf(print_mesh.vertices, faces, output.name, directory / "model.3mf")
    # Validate the actual float32 printing geometry too; preserve topology and do not repair.
    stl = trimesh.load(directory / "model.stl", force="mesh", process=False)
    if not np.all(np.isfinite(stl.vertices)):
        raise ValueError("STL contains non-finite vertices")
    # STL has no vertex indices: weld its coincident vertices for incidence tests.
    # Do not delete triangles, fill holes, change winding, or repair intersections.
    stl.merge_vertices(digits_vertex=8)
    stl_mesh, stl_validation = validate_mesh(stl.vertices, stl.faces, expected_euler=expected_euler)
    if len(stl_mesh.faces) != len(faces):
        raise ValueError("STL serialization changed the triangle count")
    wrapper = lib3mf.get_wrapper()
    exported = wrapper.CreateModel()
    exported.QueryReader("3mf").ReadFromFile(str(directory / "model.3mf"))
    if exported.GetUnit() != lib3mf.ModelUnit.MilliMeter:
        raise ValueError("3MF units are not millimeters")
    objects = exported.GetMeshObjects()
    objects.MoveNext()
    obj = objects.GetCurrentMeshObject()
    three_mf_vertices = np.array(
        [list(obj.GetVertex(i).Coordinates) for i in range(obj.GetVertexCount())]
    )
    three_mf_faces = np.array(
        [list(obj.GetTriangle(i).Indices) for i in range(obj.GetTriangleCount())]
    )
    _, three_mf_validation = validate_mesh(
        three_mf_vertices, three_mf_faces, expected_euler=expected_euler
    )
    if len(three_mf_faces) != len(faces):
        raise ValueError("3MF serialization changed the triangle count")
    # Lighter display mesh: same continuous equations, normal offset and plane trims.
    pa = a // 2 if (a // 2) % (2 * surface.flute_count) == 0 else a
    pv = max(16, v // 2)
    if master:
        vp, fp, np_, flat, edges = sample(surface, master, pa, pv)
    else:
        vp, fp, np_, _ = sample_mesh(surface, pa, pv)
        edges = []
        for start in (0, pv * pa, (pv + 1) * pa, (2 * pv + 1) * pa):
            ring = vp[start : start + pa]
            for left, right in zip(ring, np.roll(ring, -1, axis=0)):
                edges.extend((left.tolist(), right.tolist()))
        side_faces = 4 * pa * pv
        flat = [
            {"start": side_faces, "count": 2 * pa, "normal": [0, 0, -1]},
            {"start": side_faces + 2 * pa, "count": 2 * pa, "normal": [0, 0, 1]},
        ]
    preview = {
        "units": "mm",
        "parts": [
            {
                "name": output.name,
                "color": output.color,
                "material": output.material,
                "vertices": vp.tolist(),
                "triangles": fp.tolist(),
                "normals": np_.tolist(),
                "edges": edges,
                "flat_normals": flat,
            }
        ],
    }
    tooling = None
    if doc.casting_box:
        from cad.casting_box import artifacts as tooling_artifacts

        tooling = tooling_artifacts(doc, surface, directory)
        preview["parts"].extend(tooling["previews"])
    (directory / "preview.json").write_text(json.dumps(preview, separators=(",", ":")))
    render(preview, directory)
    if tooling:
        exploded = {"units": "mm", "parts": []}
        for part in preview["parts"]:
            offset = np.array(part.get("exploded_offset", [0, 0, 0]))
            exploded["parts"].append(
                {
                    **part,
                    "opacity": 1,
                    "vertices": (np.array(part["vertices"]) + offset).tolist(),
                    "edges": (np.array(part["edges"]).reshape(-1, 3) + offset).tolist(),
                }
            )
        render(exploded, directory, views=[("exploded", 30, -55)])
    bounds = mesh.bounds
    measures = {
        "bounds": {"min": bounds[0].tolist(), "max": bounds[1].tolist()},
        "x": float(mesh.extents[0]),
        "y": float(mesh.extents[1]),
        "z": float(mesh.extents[2]),
        "volume": float(mesh.volume),
        "area": float(mesh.area),
        "solid_count": 1,
        "valid": True,
        "measurement_basis": "validated printing mesh; not an exact B-rep",
        "export_triangles": len(faces),
        "role": "one-piece filled master, collar and lipped base"
        if master
        else ("reference dripper — not an exterior mold master" if tooling else "finished dripper"),
    }
    checks = []
    for check in doc.checks:
        actual, expected = measures[check.metric], expressions.value(check.expected)
        checks.append(
            {
                **check.model_dump(),
                "actual": actual,
                "expected": expected,
                "passed": abs(actual - expected) <= check.tolerance,
            }
        )
    report = {
        "units": {"length": "mm", "area": "mm²", "volume": "mm³"},
        "parameters": expressions.resolved,
        "parts": {output.name: measures, **(tooling["parts"] if tooling else {})},
        "checks": checks,
        "valid": all(c["passed"] for c in checks),
        "analytic_surface": analytic,
        "mesh_validation": topology,
        "export_validation": {"stl": stl_validation, "3mf": three_mf_validation},
        "representation": "analytic parametric source + sampled solid-master boundary"
        if master
        else "analytic parametric source + sampled normal-offset mesh",
        "limitations": [
            "STL/3MF are triangulated approximations of the continuous equations.",
            "STEP and DXF are not implemented for this analytic generator.",
            "Master sampling is not a certified global approximation bound."
            if master
            else "Centroid error checks are sampled, not a global approximation bound.",
        ],
    }
    if tooling:
        report["casting_box"] = tooling["report"]
    (directory / "validation.json").write_text(json.dumps(report, indent=2))
    return {
        "report": report,
        "exports": {
            "stl": "model.stl",
            "3mf": "model.3mf",
            **(tooling["exports"] if tooling else {}),
        },
        "engine": {
            name: importlib.metadata.version(name)
            for name in (
                "numpy",
                "trimesh",
                "lib3mf",
                "pymeshlab",
                "build123d",
                "cadquery-ocp-novtk",
            )
        },
        "tessellation": {
            "angular_samples": a,
            "vertical_intervals": v,
            "preview_angular_samples": pa,
            "preview_vertical_intervals": pv,
        },
    }
