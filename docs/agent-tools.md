# CAD agent tools

The web pi agent has 17 custom CAD tools, plus its regular container-local coding tools. These do not grant deployment access. Geometry remains declarative, builds remain bounded and publication remains explicit.

## Read and navigate

| Tool | Contract |
| --- | --- |
| `cad_capabilities` | Live casting-box limits, cross-constraints, export caveats and service scope. Uses the same limit constants as validation. This is not an exhaustive list of geometric constraints. |
| `cad_schema` | Complete document JSON schema, or `section=casting_box/solid_master/feature` with referenced definitions. Runtime limits must also be consulted. |
| `cad_example` | Example enclosure source, not the current design. |
| `cad_inspect` | Compact working header (`current_commit`, counts; no full history/notes). `view=document` gives source; `view=diagnostics` gives result/failure details. `view=history` paginates `history_kind=publications/builds/commits/assets` with `offset/limit`; optional `commit` filters assets. Commits/assets are newest first, and asset lists omit instructions. `view=asset, asset_id=...` reads one attachment including its note. Build history remains limited to the latest 100 entries. |
| `cad_tree` | Required immutable revision; optional node ID and maximum depth. Includes output parts, source-feature DAG references, integrated interfaces and mating relationships. |
| `cad_component_inspect` | Required revision and exact node ID from the tree. Returns parameter expressions/resolved values, conservative consumers, linked relationships, instructions and available whole-part measurements. |

Tree IDs distinguish `part:wall_left`, `feature:...`, `interface:wall_left:front_rail` and `joint:slide_lock_front`. Rails are integrated into wall parts, not extra printable solids. A joint references its clip and both mating rail interfaces without duplicating physical parts. IDs are design-local and name-based; renaming a source feature/part changes its ID. No project/component release identity is invented.

Generic feature dependencies come from the document DAG. Specialized generator interfaces are explicit metadata in `cad/introspection.py`. Their parameter references are conservatively collected from the generator source scope—not symbolic proof that every parameter changes every part. Missing measurements on failed/unbuilt candidates or logical interfaces are not represented as zeros.

The browser uses the same `/api/revisions/{revision}/tree` and `/components/{id}` data as pi. The authenticated gateway admits only published revisions for these routes; pi's private API can inspect its unpublished candidates. Component lookup is read-only and does not publish, restore or select a server-global model.

## Build and inspect candidates

| Tool | Contract |
| --- | --- |
| `cad_build` | Full `document_json` and `expected_generation`. Optional stable `request_key` and `wait=false`. Returns candidate ID, status, base generation and next steps rather than dumping every report. |
| `cad_parameters` | Nonempty object of changes to existing **design-global** parameters, applied to the explicit working document (or legacy publication if no working commit exists). Requires the current workspace generation when there is a design commit. Same generation/idempotency/wait controls. No implicit new parameters or edits to historical selections. |
| `cad_cancel` | Explicit revision. Cancels queued/running work; finished work is reported without changes. It never rolls back a publication. |
| `cad_measure` | Whole-part measurements and assembly dimensions; optional part filter. Retains measurement basis. Analytic masters use validated mesh measurements, not exact B-reps. Part volume is not automatically plaster-cavity volume. |
| `cad_validate` | Summary by default; sections `checks`, `mesh`, `exports`, `assembly`, `all`. Explicit coverage distinguishes `passed`, `failed`, `not_checked`, and legacy metric-only `reported` (no invented verdict). A missing section has `valid: null`, never inherits geometry validity. Summary `valid` is retained for compatibility and applies ONLY to geometry/declared assertions; `geometry_valid` and `valid_scope` make this explicit. No printability/strength certification. |
| `cad_render` | Actual revision-bound images sent to the model. Defaults to `view=review` (iso/top/front plus optional exploded); single views and inspection/standard styles are available. See [automatic visual checkpoints](visual-review.md). |

If submission is uncertain, the error contains its request key: inspect history or retry identical input with that key. If a known candidate is still running after the wait budget, poll it instead of submitting another. A polling/network failure does not silently cancel a candidate. Explicit agent abort requests cancellation when the candidate ID is known; inspect state afterward because cancellation may race with completion.

## Publish and deliver

| Tool | Contract |
| --- | --- |
| `cad_commit` | Actual design changes only. Requires concise `name`, Unicode `icon`, `source_file`, original workspace generation and `base_revision`. Reads clean project Git HEAD; normalized committed JSON must match the immutable ready CAD result. Idempotent; does not publish. Visual checkpoint required. |
| `cad_attach` | Attach a named `inspection`, `print`, or `test` output to a design commit. No working-pointer or timeline change. Explain manufacturing omissions, orientations and limitations in the note. |
| `cad_publish` | Ready validated candidate plus expected generation. Verify measurements, assembly/export checks and renders first. The service checks that candidate base generation still matches; do not bypass stale work by merely changing the number. |
| `cad_restore` | Explicit earlier publication plus current generation. Creates a new publication; browsing is never permission to restore. |
| `cad_export` | Without format, lists available export keys/files. With format, resolves a specific artifact and manifest. Includes an authenticated website-relative download path; the internal loopback URL is not a public share link. Does not send files externally. |

Primary tool summaries are bounded JSON; visual checkpoints add captioned image/text blocks. First summary inspections and successful builds automatically attach views. Publish/restore first return `visual_review_required` without mutation if this extension instance has not delivered that revision's mandatory views; inspect and explicitly retry. Oversized JSON output is wrapped in a valid truncation envelope with `full_output_path`, a mode-0600 JSON file in a private temporary directory. Read it with offset/limit; narrower selectors remain available. It is never silently treated as complete. File credentials and provider tokens are not part of these responses.

## Extrusion compatibility

Use `extrude_z` for NEW XY profiles when positive height must mean local +Z regardless of winding. Placement/rotation is applied afterwards. Legacy `extrude` retains its original winding-dependent direction to preserve existing source geometry and hashes: clockwise profiles extend along local -Z and new reports include a warning. No legacy documents or immutable exports are migrated. Do not mechanically rename old operations without reviewing the resulting geometry. `cad_capabilities` advertises this distinction and the feature/profile/operand limits.

## Validation

`tests/test_kernel_regressions.py` covers disconnected multi-operand Booleans, empty intermediates, explicit direction and legacy winding. `node --test scripts/cad-presentation.test.mjs` tests bounded navigation and honest validation coverage. The real loader test also simulates 150 large attachment notes and checks private-file fallback.

`tests/test_introspection.py` checks stable unique IDs, valid relationships, generic dependencies, shared parameters, missing measurements, API lookup and published-only gateway access. `scripts/test-pi.mjs` loads the actual pi extension and exercises all 17 tools, including idempotent submission, history pages, early cancellation and no-op cancellation of completed work. Run that script against an **isolated** data directory/port: it intentionally builds, publishes and restores test models. Never run it against live project data. Browser tests check that the tree follows an immutable revision and stale component responses cannot overwrite newer selections.
