# Reusable component library

Status: requested product scope / implementation plan. No component catalog or insertion UI is deployed yet.

## Purpose

Keep reusable engineering knowledge alongside reusable geometry. A component is a versioned parametric definition with instructions, source and validation—not merely an STL, and not necessarily just one printed part. Components belong to the workspace library and can be instantiated in multiple project designs.

## Contents of a released version

- Stable component ID, human-readable name, description, tags and immutable version/content hash.
- Editable source: declarative geometry or a reference to a reviewed, installed generator. Include source Git provenance, generator/engine version requirements and license/attribution where applicable.
- Parameter schema: types, units, defaults, valid ranges, relationships and explanations. Distinguish editable inputs from derived dimensions.
- Named output parts and mating interfaces: local coordinate system, placement anchors, insertion/removal direction, contact faces, clearance conventions and required surrounding space.
- Instructions: when to use it, how to instantiate it, assembly/removal sequence, printing orientation, possible supports, fit calibration and known limitations.
- Example configurations and a small test assembly. Preview and downloads are generated from a specific version and parameter set, not treated as the editable source.
- Validation cases: default dimensions, representative boundaries, invalid combinations, mating/interference checks and export checks. Clearly separate computational checks from physical testing.

Source, parameter definitions, instructions and tests are Git-tracked. Generated artifacts belong in immutable artifact storage; credentials, databases and conversations do not belong in component packages.

## First entry: printed slide-lock joint

Extract the existing design from `cad/casting_box.py` rather than making an unmaintained copy of its geometry. Initially document the existing implementation; a reusable generator is released only after extraction and regression tests.

Treat the slide clip and its matching pair of triangular rails as a joint family. The clip alone is a named output, but cannot be parameterized independently of its mating rails.

Document at least:

- Current clip length: 100 mm, plus a 3 mm stop cap.
- Current clip wall thickness: 3 mm; mating clearance: 0.15 mm **normal to the mating faces**, not an interchangeable horizontal or vertical gap.
- Current rail depth and half-width: 8 mm each; rail underside ramp: 3 mm.
- Rail length, engagement, end-stop location and removal envelope as coupled design inputs/derived constraints. Distinguish these assembly-dependent values from universal defaults.
- Zero-gap loaded stop contact versus clearance on sliding surfaces.
- Named clip/rail outputs, placement frames and host attachment requirements. Rails must be integrated into sufficiently supported host walls; do not imply a free-standing rail is an adequate attachment.
- Print orientation, support requirements, deburring and a short fit-test coupon before full-length printing.
- Validation of sliding clearance, stop contact and retention against wall separation. Strength, fatigue, printer fit and leak-tightness remain physically unverified.

The captured floor joint in `cad/captured_base.py` is a separate potential component: floor flange, wall channel, horizontal seat and retaining shoulder. Do not conflate its 2.062 mm roof overhang or base sealing limitations with the slide clip itself. Its instructions must retain the support warning and dry-fit/water-test requirements.

Existing designs and historical meshes remain unchanged during extraction. The existing locking assembly is the regression reference, not an excuse to silently modify the approved base.

## Reuse and versioning

A design instance records component ID, exact released version/hash, parameter overrides, placement and a stable instance ID. Named outputs receive instance-scoped IDs so using two locks does not cause part-name collisions.

- Keep old versions available for historical builds; archiving a catalog entry must not remove referenced versions.
- Updating the library never rewrites existing instances. Upgrading is an explicit candidate build, with parameter migration/diff, validation and explicit publication.
- Record the fully resolved component source/parameters/dependencies with each CAD revision, plus engine provenance. A historical build must not resolve a moving `latest` reference.
- Bound instance counts and dependency depth, reject dependency cycles and use the existing globally bounded worker queue.
- Copying/customizing a component creates an explicit fork with provenance, not an invisible edit of a shared release.
- Shared design access does not automatically grant access to other designs that use the same component or to unrelated private library source.

## Browser and pi workflow

A **Components** workspace section provides search/tags and component pages with **Overview**, **Parameters**, **Instructions**, **Source**, **Examples** and **Validation**. Show release/version and physical-test status prominently.

“Use in design” requires an explicit target project/design, version, parameters and placement. It prepares an instance/candidate; it does not publish automatically. The viewer can isolate the component and its mating parts to inspect the fit. Parameter editing may be a form or a pi request; both use the same validated schema and candidate pipeline.

Pi needs tools to list/search components, inspect a version including its instructions and schema, and instantiate or explicitly upgrade it in a named design. Instructions are reference material, not authority to execute embedded shell commands. Generator code changes require review/tests and an explicit application rebuild/deployment; component insertion must never execute arbitrary uploaded Python or dynamically import user-supplied paths.

## Delivery order and acceptance

1. Alongside project/design storage: define library/version/instance metadata and seed the slide-lock documentation, schema, source references and examples. Existing documents stay self-contained until resolution is implemented.
2. Add the library browser and pi discovery/inspection tools. Clearly label documentation-only entries that cannot yet be instantiated.
3. Extract and register the slide-lock generator, implement pinned instance resolution and candidate insertion/upgrade, then run geometry regressions before releasing it.
4. Add captured-floor joints and other components only with their own interfaces, instructions and tests.

Acceptance: persistence across restart; parameter validation; default and boundary fit tests; two differently sized instances in one design without ID collisions; reuse across independent projects; no implicit upgrades or publication; historical versions remain resolvable; provenance is recorded; access checks hold; approved baseline geometry is preserved. The catalog alone is not completion of reusable geometry support.
