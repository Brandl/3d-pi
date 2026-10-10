# Full material sections

`cad_section` is a read-only design inspection tool backed by the standalone Python submodule `cad.sections`. By default it sections **existing immutable STEP geometry**, not a rebuilt document or a flattened camera view. Holes and disconnected material regions are retained, each selected part independently. Explicit `representation:"mesh"` instead sections the immutable assembly preview mesh; all outputs and measures are labelled **approximate**, never exact analytic geometry.

```json
{
  "revision": "<revision returned by cad_inspect>",
  "axis": "y",
  "offset": 5,
  "tilt": [0, 0]
}
```

Optional `parts` is a list of exact output names from `cad_tree` (up to 32). Omit it for the full model. Example: `"parts":["enclosure"]` (replace with a name actually returned for your model). `deflection` controls sampled outline tolerance in millimetres (default 0.02, range 0.005–0.5); kernel area and DXF curves do not depend on this display tolerance.

## Plane convention

All coordinates are in the revision's assembly/world frame, not a part-local frame.

| Axis (normal) | Initial U | Initial V |
| --- | --- | --- |
| +X | +Y | +Z |
| +Y | −X | +Z |
| +Z | +X | +Y |

1. Set origin to `offset × untilted axis`, in mm (−10000..10000).
2. Rotate V and normal about initial U by `tilt[0]` degrees.
3. Rotate U and normal about the now-rotated V by `tilt[1]` degrees.

Both rotations follow the right-hand rule; each angle is −180..180 degrees. Tilting **does not move the origin**. The returned `plane` records origin, normal, U and V explicitly. A section-space point maps to world as `origin + u*U + v*V`. For zero tilt, `axis=z, offset=5` means Z=5. With `tilt=[90,0]`, that same origin is retained and the normal becomes −Y.

The cutting face is centred on the projection of each part, so a far-away origin within the cutting plane does not accidentally crop the section.

## Results and limitations

- An inline PNG with hatched material, empty holes, named colours, axes and plane parameters.
- Authenticated PNG, SVG, DXF and JSON download links.
- Exact-kernel per-part area/perimeter, connected-region and hole counts.
- JSON closed outer/hole polygons in UV coordinates, sampled at the requested deflection.
- STEP mode: DXF curves in local XY/UV coordinates and millimetres; per-part layers are recorded in the summary.
- Explicit mesh mode: closed polygonal DXF loops and mesh-derived areas/perimeters. Uses assembly/world coordinates, not separately translated print STL coordinates. `deflection` does not refine the source mesh.
- A non-intersecting plane is a successful `empty:true` result, with an explanatory image—not a failed build.

SVG/PNG/JSON are sampled visual/outline representations. DXF preserves the kernel curves. A section is **not** a wall-thickness, collision, printability or strength certificate. The area sum counts each part independently; overlapping material is not unioned. Coplanar faces may appear and zero-area contacts are omitted.

STEP import sometimes repeats labels for reused prototype shapes. The loader matches assembly occurrences to immutable part measurements, checks cardinality, and rejects ambiguous identification rather than guessing. Mesh-only models still reject the default STEP request. Request `representation:"mesh"` explicitly to opt into approximation. Source mesh tessellation error is not a certified bound. Mesh input is capped at 64 MiB and selected parts at 500,000 triangles; open/non-volume meshes are rejected.

## Reuse a section as a build profile

`cad_section_profile` takes `revision`, `section_id`, `part`, optional `region_index`,
`boundary` (`outer` or `hole`), `hole_index`, `tolerance` (0.005–0.5 mm, default 0.02)
and `max_points` (3–512). It reads one existing cached boundary, validates closure,
simplifies without silently relaxing the requested tolerance, and returns CCW XY
points without a repeated closing vertex for `extrude_z`. Input loops are bounded
at 8192 points; document profiles allow 512 points each and 2048 total.

The points are **section-local UV**, not world XYZ. The response retains the plane,
source representation, omitted-boundary count and additional simplification error
bound. Source mesh/curve sampling error remains separate. No kerf, fit or shrinkage
offset is applied. Selecting an outer boundary does not include its holes.

Use normal `cad_build`, `cad_validate`, `cad_render` and `cad_export` on the derived
document, then `cad_attach` it as a test/print output. Do not commit a fixture as a
replacement for its parent design. These tools do not reconstruct exact surfaces
or certify physical fit.

## API and bounded execution

Private modeling API:

- `POST /projects/<project>/api/revisions/<revision>/sections` — parameters above, excluding revision.
- `GET|HEAD /projects/<project>/downloads/<revision>/sections/<section_id>/section.<png|svg|dxf|json>` — protected on the public gateway using the parent revision's normal access rules. Supports Range.

Section generation is not exposed as a public gateway mutation. Computation uses the existing geometry semaphore, an isolated worker with no credential environment, 40-second CPU/50-second wall deadline, 4 GiB address-space ceiling and bounded output. A busy worker returns 429; retry the identical request. Identical successful requests return cached results.

Derived files live under each project's `cad/sections/`, **outside** its immutable artifact directories. No design commit, working generation, publication, source file or existing export is changed. Cache entries are atomically exposed only after successful completion. Limits: 64 sections per revision, 16 MiB per section, 256 MiB per project; hitting limits does not silently delete history. Interrupted scratch directories are discarded during locked service startup.

Implementation: `cad/sections.py` (frame, STEP identity, topology, outputs), `cad/section_service.py` (worker/cache/limits), `.pi/extensions/lib/section-image.mjs` (bounded PNG delivery).
