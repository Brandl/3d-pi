# 3d-pi

A local, agent-native CAD MVP. **Pi models; Open CASCADE computes; the browser observes.**

The browser has orbit/pan/zoom and download links, but no geometry-editing controls. Pi creates named parametric features through an API, inspects candidate geometry, and explicitly publishes successful revisions.

## Quick start

Requires **Linux, Node.js 20.19+ (or 22.12+), and [uv](https://docs.astral.sh/uv/)**. Python 3.12 is pinned and can be installed automatically by uv. Network access is needed to install dependencies; the viewer uses no CDN or external assets at runtime.

```bash
uv sync --locked
(cd web && npm ci && npm run build)
uv run python -m cad.cli serve
```

Open **http://127.0.0.1:8765**. In a second terminal, create the demo:

```bash
uv run python -m cad.cli demo
```

This creates and publishes an enclosure and lid. Artifacts include STEP, STL, 3MF, an XY-section DXF of the lid, preview geometry, and three PNG views.

### Model through pi

Start pi in this directory and trust the project extension when prompted. For an already running session, use `/reload`. The extension is `.pi/extensions/cad.ts`.

Example requests:

> Build the example enclosure and lid. Check its dimensions and render it before publishing.

> Increase wall thickness to 3 mm and move the hole centers to 10 mm from each corner. Keep the outer dimensions unchanged.

> Restore the previous published design, then export STEP and 3MF.

For a CAD-only agent without pi's general shell/filesystem tools:

```bash
pi --no-builtin-tools -e .pi/extensions/cad.ts
```

`AGENTS.md` supplies the modeling conventions and verification workflow. The extension talks directly to the service; no MCP server or model credentials are needed in the CAD backend. Pi still needs its own configured model/provider for conversational use.

Set `CAD_URL=http://127.0.0.1:<port>` for the extension and CLI if running the service with `serve --port <port>`. The pi extension intentionally permits only loopback HTTP endpoints.

### Other examples

```bash
uv run python -m cad.cli build examples/bracket.json --publish
uv run python -m cad.cli build examples/mounting-plate.json --publish
uv run python -m cad.cli inspect
```

Without `--publish`, `build` only creates a candidate. The demo command explicitly publishes by design. API users and pi publish separately.

## What works

- Parameter expressions and named feature dependencies, with immutable document snapshots.
- Boxes, cylinders, polygon extrusions, boolean union/subtract/intersection, transforms, and fillets with axis-based edge selectors.
- Multiple named solid outputs with colors and placements.
- Exact bounding dimensions, areas, volumes, solid counts, kernel validity, and explicit numerical design assertions.
- Candidate builds in separate processes, bounded job queue, cancellation, deadlines, and worker resource limits.
- Atomic publication, optimistic generation checks, request-key deduplication, and restoration without deleting history.
- WebSocket-driven browser updates, reconnect recovery, CAD edge overlays, and preservation of the working geometry on failure.
- STEP, STL, 3MF, and named XY-section DXF exports bound to exact revisions.
- Revision-bound isometric, top, and front PNG inspection images.
- Seventeen native pi tools (including `cad_commit` and `cad_attach`): `cad_capabilities`, `cad_schema`, `cad_example`, `cad_inspect`, `cad_tree`, `cad_component_inspect`, `cad_build`, `cad_parameters`, `cad_cancel`, `cad_measure`, `cad_validate`, `cad_render`, `cad_publish`, `cad_restore`, `cad_export`. See [tool contracts](docs/agent-tools.md).

## Analytic example: B-01 Gentle Twist

`examples/gentle-twist.json` defines the 78 mm porcelain dripper with ten cosine flutes, +20° bottom-to-top twist, and a 3 mm **analytic inward-normal offset**, trimmed to horizontal end planes. See [`examples/gentle-twist.md`](examples/gentle-twist.md) for the equations and verification results.

This specialized `gentle_twist` generator produces editable parametric source plus **STL/3MF meshes**, not an exact STEP/B-rep. The printing mesh has 185,760 triangles; a lighter 46,800-triangle preview uses analytic normals for smooth porcelain shading. The mesh and reloaded printing artifacts are checked for open/non-manifold edges, winding, degeneracy, and self-intersections using trimesh and MeshLab. No master or shrinkage compensation is added.

This generator is intentionally restricted to one origin-aligned reference output, with no mixed primitive features or DXF sections. The optional `casting_box` configuration adds four separately named B-rep tooling components. General primitive/B-rep modeling and its STEP exports continue to work as before.

### All-printed captured base

Latest: [`examples/origami-20-locking-base.json`](examples/origami-20-locking-base.json) is a **20-fold Origami-style casting master**, with 40 flat panels and zero twist. Its floor, pedestal and positive-lock flange are preserved; existing walls and clips can be reused. See [Origami notes](examples/origami-20-locking-base.md).

Previous: [`examples/gentle-twist-positive-lock-floor.json`](examples/gentle-twist-positive-lock-floor.json) adds a **2 mm flat retaining shoulder** above the floor flange, with 0.15 mm vertical clearance, and removes the misplaced pedestal-foot chamfer. The lower seat and existing slide clips retain the floor. See [positive-lock floor notes](examples/gentle-twist-positive-lock-floor.md), including the small roof-overhang printing tradeoff and reprint requirements.

Previous: [`examples/gentle-twist-pedestal-chamfer.json`](examples/gentle-twist-pedestal-chamfer.json) adds a **2 mm × 45° chamfer around the floor-to-central-pedestal junction**. See [pedestal-chamfer notes](examples/gentle-twist-pedestal-chamfer.md). Walls, clips and mating fits are unchanged.

Previous: [`examples/gentle-twist-cutting-neck.json`](examples/gentle-twist-cutting-neck.json) adds a **5 mm narrow-end extension**: 3 mm smooth blend then 2 mm straight Ø28 mm cutting neck. Both chamfers and thin-form fits are retained; unchanged walls leave 15 mm of plaster above the tip. See [cutting-neck notes](examples/gentle-twist-cutting-neck.md).

[`examples/gentle-twist-chamfered-form.json`](examples/gentle-twist-chamfered-form.json) adds **3 mm ×45° self-supporting rail underside ramps** and a **2 mm ×45° plaster-corner former** to the thin form. See [chamfer notes](examples/gentle-twist-chamfered-form.md).

Latest thin variant: [`examples/gentle-twist-thin-captured-base.json`](examples/gentle-twist-thin-captured-base.json) uses **1.5 mm curved walls and flat floor**, thicker local rim/rail reinforcement, and **0.15 mm mating clearances**. The loaded seat remains gap-free, and walls still extend 20 mm above the master. See [thin-form fit notes](examples/gentle-twist-thin-captured-base.md).

For a closed plaster cavity, use [`examples/gentle-twist-tall-captured-base.json`](examples/gentle-twist-tall-captured-base.json): the walls extend **20 mm above the master tip**, with matching longer slide locks. The master and captured floor are unchanged.

[`examples/gentle-twist-captured-base.json`](examples/gentle-twist-captured-base.json) replaces the screw/gasket option with an integral floor flange captured inside the two wall halves. Plaster weight presses the flange onto a **7 mm-wide horizontal seat**; the existing slide locks retain the halves. Five printed pieces, no purchased hardware or gasket. See [joint geometry and dry-fit instructions](examples/gentle-twist-captured-base.md). The ZIP includes an explanatory `joint-section.svg`. Water-test the printed contacts and vertical seams; no leak-tightness certification is claimed.

### Clamped and gasketed base

[`examples/gentle-twist-locked-base.json`](examples/gentle-twist-locked-base.json) adds four external M5 screw clamps, integral wall feet, and a continuous silicone-ring groove to the wide-end-down master. The Ø204 × 6 mm base stays integral with the master. Purchased hardware: four M5×20 screws/nuts and a 170 × 2 mm silicone O-ring. See [assembly, seal and water-test instructions](examples/gentle-twist-locked-base.md). Vertical seams still require sealing; geometric checks do not certify leak-tightness.

### One-piece casting master

**Recommended release orientation:** [`examples/gentle-twist-wide-end-down-master.json`](examples/gentle-twist-wide-end-down-master.json) sets `solid_master.wide_end_down: true`. The wide collar sits on the floor, with the filled dripper tapering upward. The base/lip remain integral and the walls/locks stay separate. See [draw-check and release notes](examples/gentle-twist-wide-end-down-master.md). The current analytic surface has no axial geometric undercut when lifting plaster upward from this base.

[`examples/gentle-twist-solid-master.json`](examples/gentle-twist-solid-master.json) enables `solid_master`: a filled dripper joined to a Ø136 × 20 mm top collar and Ø184 × 4 mm base with an integral locating lip. The lip seats the round wall halves with 0.3 mm radial clearance. See the [master notes](examples/gentle-twist-solid-master.md) for print orientation, dimensions, validation and demolding limitations. The master exports as STL/3MF and is included in the tooling ZIP; STEP remains hardware-only.

### Outer casting-box tooling

`examples/gentle-twist-casting-box.json` surrounds the current 40°-twist, deeper-fluted dripper with **two three-sided U-shaped walls and two dovetail slide clips**. See [`examples/gentle-twist-casting-box.md`](examples/gentle-twist-casting-box.md) for dimensions, fit checks, print orientations, and scope.

For two semicircular walls, use `examples/gentle-twist-round-casting-box.json` with `casting_box.profile: "round"`. The nominal round form is Ø168 mm inside / Ø176 mm outside, 98 mm high, with the same locks and clearances.

The viewer's **Explode** control separates the parts visually. Each hardware component has a print-oriented STL/3MF and an assembled-position STEP. A tooling ZIP bundles all four components; the dripper remains a separate, unchanged reference. Named exports use `?part=wall_left`, `wall_right`, `lock_front`, `lock_back`, or `casting_box` (STEP assembly/ZIP), also supported by `cad_export`.

This is outer formwork, not a finished porcelain slip-casting mold: a prepared exterior master, sealed base, plaster parting/release plan, and measured shrinkage/process data remain necessary.

## Architecture

```text
pi extension / CLI
        │ HTTP: document → build → inspect → publish
        ▼
FastAPI ── SQLite revisions + published generation
        │
        └── single active geometry worker process
             ├── bounded JSON interpreter
             ├── build123d / Open CASCADE
             └── mesh, edges, exports, renders, manifest
        │
        └── WebSocket state snapshots + artifact HTTP URLs
                   ▼
          TypeScript / Three.js viewer
```

### Deliberate MVP scope change

The roadmap originally proposed editable Python source and OS-sandboxed execution. This implementation instead accepts **a small declarative JSON document**, interpreted by trusted Python code. It is not an arbitrary Python execution endpoint. This makes a useful local vertical slice possible without pretending subprocess limits are a security sandbox.

The document is the parametric source of truth, not the preview mesh or conversation. JSON schema version 1 is exposed at `/api/schema`; unsupported versions and unknown fields are rejected. See `examples/` and `AGENTS.md` for syntax.

- Millimeters, right-handed coordinates, Z up.
- Expressions: numbers, named parameters, `+ - * /`, parentheses. No `eval`, function calls, attribute access, powers, or imports.
- Dependencies between parameters can refer forward but cannot cycle. Features reference only earlier features.
- Box origin is its minimum corner. Cylinder origin is the center of its bottom face.
- Rotation in degrees applies before translation to each feature result.
- Axis-based fillet selectors select **all** matching edges, not one guessed edge. They fail on empty selections. Persistent face/edge naming is not solved.
- Parameters are numeric scalars, not a dimensional-analysis/unit-typed system. Only mm documents are supported.

### Limits and deployment boundary

This is **one single-owner installation, folder-backed projects, and one active geometry worker**. Each project has its own history/generation, source Git repository and pi transcripts. The global queue is bounded to eight tasks, with the existing four-job per-project bound. Default CAD storage is `data/`; change it with `CAD_DATA_DIR`. See [folder projects and migration](docs/projects.md).

- 100 features, 16 output parts, 64 parameters, 100 polygon vertices, 16 DXF sections, 64 assertions.
- 256 KiB request bodies; expressions at most 160 characters / 64 AST nodes.
- Primitive lengths 0.01–2000 mm; polygon coordinates ±2000 mm; translation ±5000 mm; rotation ±360°; feature extents at most 10000 mm.
- Linear tessellation tolerance 0.01–1 mm (default 0.1); angular tolerance 0.05–0.8 radians (default 0.2).
- Preview cap of 300,000 triangles per output.
- Worker CPU soft/hard limits 75/80 seconds, wall deadline 100 seconds, virtual address space 6 GiB, individual output file limit 128 MiB.

The service binds to loopback, checks Host and Origin, does not enable CORS, accepts no filesystem paths in documents, and exposes only allowlisted artifacts. Worker environment variables are allowlisted; pi credentials are not inherited.

**Never expose the modeling API publicly.** It has no user authentication. In the Podman deployment its host port remains loopback-only; the authenticated gateway is the only public entry point. Containers add filesystem/network boundaries and resource limits, but this is a trusted single-owner workspace, not a multi-tenant sandbox or a disk quota system. Native kernel vulnerabilities remain possible. Pi can run commands and edit files inside its own container and mounted workspace.

## Export semantics

| Format | Contents / limitations |
|---|---|
| STEP | Exact solid geometry and named outputs in their modeled placements. Not the original parametric feature history. |
| STL | All output solids tessellated at the recorded tolerances. Coordinates mean mm; STL cannot encode units or part metadata reliably. |
| 3MF | Separate mesh objects, mm units, and part labels via build123d's lib3mf exporter. Not slicer settings or exact CAD surfaces. |
| DXF | A named output cut by a world-space XY plane at `sections[].z`, flattened to z=0 while preserving world XY placement. Not a projection or sheet-metal unfold. |

All exports are produced eagerly during a build. A section/export failure fails the candidate rather than publishing a partially built artifact set. Numerical assertion failures remain inspectable but cannot be published or downloaded as manufacturing exports.

`manifest.json` records revision, document hash, engine versions, build duration, checks, and tessellation settings. `document.json` is the rebuildable source. Artifact bytes are not guaranteed identical across rebuilds (e.g. timestamps/UUIDs); numerical geometry is regression-tested.

Tests check watertightness and dimensions of the sample printing exports with trimesh and inspect DXF with ezdxf. STEP is round-tripped through OCCT. These are not certifications of arbitrary models, printer compatibility, minimum wall thickness, mechanical strength, or comprehensive manufacturability.

## API

Interactive API docs: http://127.0.0.1:8765/docs

| Endpoint | Purpose |
|---|---|
| `GET /api/state` | Published revision, generation, latest 100 builds and all publications |
| `GET /api/schema` | Full document JSON schema |
| `GET /api/example` | Enclosure document |
| `POST /api/builds` | `{document, expected_generation, request_key}` → queued revision (202) |
| `GET /api/revisions/{id}` | Source, status, report, errors, provenance |
| `POST /api/revisions/{id}/cancel` | Cancel queued/running work |
| `GET /api/revisions/{id}/report` | Measurements and checks |
| `POST /api/revisions/{id}/publish` | `{expected_generation}`; passing candidate built at that generation |
| `POST /api/revisions/{id}/restore` | `{expected_generation}`; previously published revision |
| `GET /api/revisions/{id}/export/{format}` | Download metadata; DXF uses `?section=name` |
| `GET /api/revisions/{id}/artifacts/{filename}` | Allowlisted artifact download |
| `WS /api/events` | Current state on connect, changes, and every ten seconds |

A build moves `queued → building → ready / failed / cancelled`. Ready does not imply assertions passed: check `result.report.valid`. Publication does not change the immutable candidate's build status.

Every publish/restore increments a generation, even if the model was seen before. A stale candidate cannot overwrite newer work; restore uses a distinct operation. Reusing a build request key with identical input returns the same revision; a different input gives 409. Retrying the immediately successful publication is also idempotent. After an interrupted build, use a new request key to retry.

## Tests

```bash
uv run pytest -q
uv run ruff check cad tests
uv run ruff format --check cad tests
(cd web && npm run build)
```

Browser and pi smoke tests require a running service and **create/publish test revisions**. Prefer a separate data directory/port:

```bash
CAD_DATA_DIR=/tmp/3d-pi-test uv run python -m cad.cli serve --port 8766
# In another terminal:
(cd web && npx playwright install chromium)
(cd web && CAD_URL=http://127.0.0.1:8766 npm test)
CAD_URL=http://127.0.0.1:8766 node scripts/test-pi.mjs
```

The pi smoke test loads and calls the real extension tools without an LLM. It uses the installed pi loader; if pi isn't under `npm root -g`, set `PI_PACKAGE_DIR` to its package directory. An actual model-driven conversation is not part of the automated tests.

Test coverage includes parameter changes, actual hole locations, primitive/fillet geometry, all export readers, cancellation, duplicate requests, stale publication, failed builds/assertions, worker crash reporting, restart recovery, origin/host checks, artifact allowlisting, live viewer updates, and restoring previous revisions.

For viewer development: run the backend, then `cd web && npm run dev`. Vite proxies `/api` to port 8765. Rebuild `web/dist` before using the backend's production viewer.

## Persistence and backup

Stop the service cleanly, then copy the entire `data/` directory (including SQLite sidecars if present and all `artifacts/`). Restore it to a new `CAD_DATA_DIR` using the same locked environment. Only one service may open a data directory; a file lock enforces this on Linux. Queued/building revisions are marked failed after a restart; the published pointer is retained.

There is no automatic artifact cleanup or retention limit. History responses show the most recent 100 entries, but older revisions remain available by ID. Monitor disk space; do not manually remove artifacts for revisions you need to restore.

## Still out of scope

- Arbitrary Python source execution / production OS sandboxing.
- Rich sketch constraints, revolve/loft/shell/chamfer operations, general patterns, and assembly mates.
- STEP import, persistent topological naming, projection DXFs, sheet-metal unfolding.
- Multiple users, multiple designs within one project, automatic cache/garbage collection. Folder projects and single-owner authentication are implemented.
- Browser-integrated chat, MCP adapter, agent control of the live browser camera, contextual picking.
- Photorealistic or occlusion-perfect inspection renders; PNGs are basic orthographic-style views of tessellated geometry.

See `todo.md` and `milestones.md` for the longer-term plan and current progress. This is a working vertical slice, not completion of every roadmap item.

## History and checkpoints

The bottom **Design timeline** shows named, Unicode-icon-labelled design commits and labelled legacy publications. Click or step through entries; **Working design** returns to the explicit editing head. Browsing never restores or commits. New builds and fixtures cannot take over the model. Related inspection views use the representation selector; named print/test sets and downloadable instructions live in **Files**. Part selection is shared with pi, and WebGL offers visual section clipping (not a capped B-rep section or changed export).

Application code, tests, documentation and parametric examples are tracked in local Git. `cad-prototype-v0` tags the working prototype before the workspace migration. Commit verified milestones regularly. The CAD timeline is not the application Git log. New design commits bind a clean project Git source JSON to a matching immutable CAD revision; old publications are not fabricated Git commits. See [project and commit contracts](docs/projects.md).

Runtime databases and generated artifacts are deliberately excluded from Git and still need backups. A Git checkout alone does not restore runtime data; inspecting old code in a separate worktree avoids changing a running service. No Git remote is configured automatically.

## Password-protected website and containerized pi

The gateway now **fails closed without a configured password**. Every preview, artifact, asset, WebSocket and agent endpoint requires authentication. The website includes a persistent pi conversation; authenticated prompts can change models through pi's CAD tools. This is a single trusted owner's interface, not anonymous sharing or multi-user accounts.

The shared workspace keeps the physical model, parts and pi conversation together. History sits below the model; there is no prescribed stage sequence. **Files** includes named outputs, instructions, project-scoped reference uploads with editable notes, other build previews, the transcript and **Components** reference library. Uploads accept up to 10 MiB per file (512 MiB / 500 files per project), remain separate from CAD history, and are downloaded rather than automatically opened or executed; see [project uploads](docs/projects.md#project-uploads). Parameter requests and historical restores can be drafted to pi without silently mutating the model. Persistent component releases/instances remain planned; see [component-library scope](docs/component-library.md).

Pi automatically receives multi-view image checkpoints on first inspection and successful builds. New builds include distinct-colour inspection renders with part legends; old revisions use their existing images. Publication remains explicit, and dotted hidden-line rendering is not implemented. See [visual review behaviour](docs/visual-review.md).

See [container deployment, credentials, backups and rollback](docs/container-deployment.md). For gateway-only development:

```sh
uv run python -m cad.auth /secure/location/password.json
CAD_PASSWORD_HASH_FILE=/secure/location/password.json uv run uvicorn cad.preview:app --host 127.0.0.1 --port 8767
cloudflared tunnel --url http://127.0.0.1:8767
```

Tunnel **only the gateway**, through HTTPS, never the private modeling API or agent bridge. A Quick Tunnel address is temporary; possession of its URL no longer grants access. `/downloads/latest.zip` and `/downloads/{revision}/{filename}` retain GET/HEAD, ranges and attachment filenames but now require login. The gateway serves legacy publications and authenticated project candidates/registered outputs, but does not directly proxy CAD mutation routes. Geometry changes go through the authenticated agent. Polling/PNG fallbacks and non-mutating historical browsing remain available.

## Dependency licensing

The application uses build123d (Apache-2.0) over OCCT (LGPL-2.1 with its additional exception), Three.js (MIT), FastAPI (MIT), lib3mf (BSD-2-Clause), trimesh (MIT), and PyMeshLab/MeshLab (GPL-3.0), among other dependencies. The new analytic mesh validation path introduces a GPL dependency; evaluate that explicitly before redistribution. Lockfiles capture versions, not legal clearance. Review upstream license files and redistribution obligations before distributing bundled native libraries or a commercial release.
