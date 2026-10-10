# 3d-pi

**A conversational CAD workspace.** Describe a model, inspect live 3D results,
refine it with pi, and save revision-bound designs and exports.

**Experimental alpha · self-hosted · one trusted owner · source-only release**

Pi works with declarative model documents; build123d/Open CASCADE computes the
geometry; the browser shows the model, conversation, history and files. The agent
also has shell and file tools in its container workspace. This is not an anonymous
CAD service or a sandbox for mutually untrusted users.

## What the alpha does

- Persistent project conversations and separate project source repositories.
- Parametric, multipart models with named features, outputs and checks.
- Live previews of passing builds, clearly labelled **Intermediary · not committed**.
- Explicit design commits linked to clean Git source, with immutable CAD history.
- Model/parts inspection, camera controls, a thumbnail timeline and mobile panes.
- Named print/test outputs, instructions, reference uploads and transcript downloads.
- STEP, STL, 3MF and section DXF exports where supported by the model; exact
  material sections of immutable STEP geometry via the agent.
- Password-protected studio, downloads and agent requests through an HTTPS gateway.

A successful build is **not** proof of printability, physical fit, strength or
mechanical safety. Review exports and use appropriate physical tests before making
or relying on a part.

## Start here

### Conversational studio

For the browser with persistent chat, follow the
[container installation guide](docs/container-deployment.md). You need Linux,
rootless Podman, Git and a supported model-provider account. Images are built
locally; no prebuilt runtime is distributed.

### Local CAD/API development

This smaller setup runs the geometry service and viewer, **not** the authenticated
chat gateway. Keep it on loopback. It needs Git, Node.js 24, Python 3.12 and
[uv](https://docs.astral.sh/uv/); uv can install the pinned Python version.
Minimal Linux installations also need native libraries such as `libgl1`,
`libglib2.0-0`, `libgomp1` and fonts; the [Containerfile](Containerfile) lists the
Debian runtime dependencies used by the local container recipe.

```sh
uv sync --locked
(cd web && npm ci && npm run build)
uv run python -m cad.cli serve
```

Open `http://127.0.0.1:8765`. In another terminal:

```sh
uv run python -m cad.cli demo
```

The demo builds and **explicitly publishes** a built-in teaching enclosure and
separate lid. It does not load excluded personal examples. Use a fresh data root
for experimentation, not an existing design workspace:

```sh
CAD_DATA_DIR=/absolute/path/to/new-cad-data uv run python -m cad.cli serve --port 8799
# In another terminal:
CAD_URL=http://127.0.0.1:8799 uv run python -m cad.cli demo
```

For a normal candidate build, save your own schema-valid JSON document and run
`uv run python -m cad.cli build /path/to/document.json`. Without `--publish`, it
does not move the saved publication pointer. `/api/schema`, `/api/capabilities`
and `/api/example` provide the current document contract, limits and teaching model.

### Use a local pi session

With the local CAD service running, start a configured pi installation in this
repository and trust `.pi/extensions/cad.ts` when prompted. Use `/reload` in an
existing session. Set `CAD_URL` to the correct **project-scoped loopback URL**;
never remove a supplied `/projects/<id>` prefix.

For example:

> Make a small two-part box and lid. Inspect dimensions and clearances, show the
> result, and save the design with its source. Do not publish it.

Pi needs its own provider authentication. The CAD service does not need model
credentials. See the [18 CAD tool contracts](docs/agent-tools.md) and
[modeling guidance](AGENTS.md).

## Preview, save and make

1. Select or create a project, then describe the intended change.
2. **Live** follows completed builds whose declared geometry checks pass. Failed
   or unfinished builds do not replace the last good preview.
3. A design commit saves a matching, clean source document and moves the working
   head. Merely viewing an intermediary does not save it.
4. **Working design** follows saved commits only. Selecting older history pins
   the view; **Live** resumes previews. Browsing never restores or publishes.
5. **Make** contains named output sets and instructions. During an uncommitted
   preview, those saved sets need not match the viewed model. Other build exports
   are not automatically approved manufacturing files.

Enter sends chat; Shift+Enter inserts a newline. Drafts and uncertain submissions
are retained per project and browser tab. Use **Check / retry** for an uncertain
submission instead of creating a duplicate request. Stopping or timing out a turn
**does not roll back** source, builds, commits or attachments already created.

## Alpha boundaries

- One trusted owner; one active agent worker and one geometry worker, not a
  multi-user isolation boundary.
- Bounded declarative geometry rather than arbitrary Python sent to the CAD API.
  The feature limit is 100; consult live capabilities for the remaining limits.
- Multi-step saving and output registration are not a resumable atomic transaction.
- Persistent face/edge selection, general thickness/clearance analysis and a
  versioned component-instancing system are not implemented.
- Some specialized generators are mesh-only; they do not provide exact STEP or
  exact material sections. Shaded views are not hidden-line drawings.
- APIs, UI and storage may evolve. Back up before upgrades; stable hosting,
  boot supervision, disk capacity and off-machine backups are operator duties.

## Documentation and development

- [Documentation index](docs/README.md)
- [Projects and provenance](docs/projects.md)
- [Studio and live previews](docs/studio-ui.md)
- [Contributing and isolated tests](CONTRIBUTING.md)
- [Security and reporting](SECURITY.md)
- [Source-only release checklist](docs/source-release.md)

Historical personal examples, UI prototypes and planning/audit records are not
part of the alpha source distribution. Their local exclusion does not erase old
Git history. Do not publish a private repository's history without a separate
review or an approved clean initial snapshot.

## License

Original project material is licensed under [Apache-2.0](LICENSE). Dependencies,
fonts and user designs retain their own terms. See [third-party notices](THIRD_PARTY_NOTICES.md).
Pi's MIT licence is compatible with the project licence; that does **not** make a
combined runtime Apache-only. In particular, redistributing PyMeshLab/OCCT and
native dependencies requires a separate GPL/LGPL compliance review.
