# Projects and design provenance

A project has one saved working design, independent CAD history, source Git
repository and agent conversation. This is a single-owner organization feature,
not a multi-tenant filesystem sandbox.

## View versus saved state

The URL `?project=<id>` binds the browser's viewport and chat. Project switching
and history browsing never publish or restore. Another tab cannot retarget an
in-flight agent turn. One agent worker is active at a time; a busy turn blocks
new prompts in other projects. Idle polling does not switch that worker.

The saved head advances only through an explicit design commit. Without one,
the latest legacy publication is the saved fallback. Separately, **Live** can
show passing uncommitted builds—even before the first commit—as labelled
intermediary states. See [studio behavior](studio-ui.md).

Workspace and publication generations are distinct optimistic-concurrency
counters. `event_sequence` orders read-only state snapshots, including build
completion and attachment events; it is not a commit count. History, head and
intermediary eligibility are read in one SQLite snapshot.

## Save a design and its outputs

`cad_commit` requires an immutable ready revision, concise name, Unicode icon,
original workspace generation/base revision and a tracked source JSON file.
The tool reads clean project Git HEAD; the service checks normalized document
identity. The private endpoint trusts its single-owner caller's Git reference:
the CAD container does not independently read the source repository.

This links source and geometry but is **not** a distributed atomic transaction.
A source commit, CAD commit and several output attachments can complete only
partially. Inspect current state after interruptions; do not reset or overwrite
history to pretend the operation was atomic.

`cad_attach` registers a named inspection, print or test output against a design
commit without moving the head. Outputs retain their own immutable documents,
exports and instructions. Registration is explicit, not inferred from filenames.
Saving a design is not publication; a historical restore appends new history.

## Storage

The default runtime root is `~/.local/share/3d-pi`; it is private and outside
application Git. Under `projects/<id>/`:

```text
project.json          # stable ID and display name
source/               # editable documents; independent Git repository
pi/sessions/          # canonical private pi session trees
pi/transcript.md      # readable event transcript
pi/requests.json      # request deduplication/interruption journal
pi/web-state.json     # bounded idle browser projection
cad                   # host-side symlink to that project's CAD storage
```

CAD storage contains SQLite state, immutable artifacts, uploads and derived
section caches. The original default project uses the legacy ID `dripper` and
root CAD storage for compatibility; new projects have generated IDs and their
own storage directories. This does not distribute a personal dripper design.

The CAD link is a host convenience; it deliberately does not grant the agent
writable access to the CAD database. Use the scoped API. A portable backup must
include the link's target, not just the symlink. Back up source Git, sessions,
databases, uploads and artifacts consistently; see [operations](container-deployment.md).

Provider credentials and website login state live in separate private global
stores, not project source. The readable transcript omits reasoning and binary
image payloads; it is not a replacement for the canonical session tree. Treat
both as private data. The website does not expose arbitrary session files.

## Project uploads

Files → Project uploads accepts an opaque file plus an optional note. Uploads
never become a CAD revision or start an agent task automatically. Files and notes
are untrusted reference data, not permission to execute or import them.

Limits are 10 MiB/file, 512 MiB and 500 files/project; notes allow 4000 characters.
Notes use optimistic versions; deleting an upload requires confirmation and does
not delete CAD outputs. Downloads are authenticated attachments, not inline HTML.

Project-prefixed routes:

- `GET /api/uploads`: list metadata and notes.
- `POST /api/uploads`: multipart `file`, optional `note`.
- `PATCH /api/uploads/{id}`: `{note, version}`.
- `DELETE /api/uploads/{id}`: delete that uploaded asset.
- `GET|HEAD /downloads/uploads/{id}/file`: download, with byte-range support.

Browser mutations require session authentication, same-origin checks and CSRF.
Avoid uploading credentials. An upload alone is not authorization to adopt it
as the current design.

## API scope and limits

Use `/projects/<id>/api/...` for state, schema, builds, revisions and inspection.
Export/download URLs retain the same project prefix. Unscoped private APIs alias
the legacy default project; unscoped gateway previews remain publication-only.
Project-scoped gateway access also permits registered outputs and eligible ready
candidates/intermediaries. Unknown or cross-project revisions are not resolved.

- `/api/projects`: GET catalog; POST `{name}` creates a project.
- `/projects/<id>/api/workspace/commits`: private design-commit mutation.
- `/projects/<id>/api/workspace/assets`: private output registration.
- `/projects/<id>/downloads/sets/<asset>/<format>`: authenticated named downloads.
- `/projects/<id>/api/agent/{state,prompt,abort,transcript}`: gateway agent routes.

The gateway does not expose arbitrary private CAD mutations. Each agent worker
receives a fixed scoped `CAD_URL`, source cwd and session directory. There is one
shared geometry worker, at most eight active/queued tasks globally and four per
project. Creating projects does not multiply worker capacity.

Project rename/archive/delete, multiple saved designs per project and versioned
component instances are not implemented. Historical installation-specific
migration scripts are not fresh-install instructions; do not apply them to an
unrelated runtime.
