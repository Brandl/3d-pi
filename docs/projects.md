# Folder projects

This first implementation has **one CAD design/history per project**. It is a
single-owner organization feature, not a multi-tenant filesystem sandbox. Multiple
designs inside one project, rename/archive/delete, component releases and atomic
Git/CAD provenance reconciliation remain future work.

## Operator workflow

The header lists projects, creates a new named project, and downloads its readable
pi transcript. The browser URL `?project=<id>` binds the viewport and chat. Opening
another tab cannot retarget an in-flight agent turn. A busy turn blocks prompts in
other projects; inactive chat polling reads a saved projection without switching
workers. One pi worker process is active at a time. Switching is not publication.

The workspace has an explicit working-design pointer and a bottom timeline of named,
icon-labelled design commits. New builds never advance it. Without a design commit,
the last legacy publication is the stable fallback; a project with neither stays
empty rather than adopting its newest fixture. Files contains named print/test sets
and a separate Other build outputs drawer. Representation selection and timeline
browsing are read-only. Legacy publication events remain labelled in history.
Historical unscoped URLs retain published-only access; project routes, candidates,
downloads and transcripts remain password protected through the gateway.

`cad_commit` requires name, Unicode icon, original workspace generation/base revision,
and a tracked source JSON file. The extension reads clean Git HEAD; the service checks
that the normalized committed JSON matches the immutable CAD document. This links
existing immutable source and geometry, not a cross-filesystem atomic transaction.
`cad_attach` registers an inspection, print or test output without moving the pointer.
Workspace and publication generations are separate. New design commits do not publish.

`design_commits`, `design_assets` and `design_state` are additive SQLite tables; original
revision/publication rows and artifacts are not rewritten. `scripts/register-workspace.py`
registers reviewed existing geometry with explicit roles through the private API. It
never builds or publishes and is repeatable after partial registration. Do not classify
old outputs by timestamp or infer roles from arbitrary titles.

The commit endpoint trusts the single-owner caller's Git reference; the installed agent
tool verifies it against its repository. The CAD container cannot independently access
the source Git mount. Ready immutable CAD documents remain the geometry source of truth.

## Files

Under `~/.local/share/3d-pi/projects/<id>/`:

```
project.json              # stable ID and display name
source/                   # editable sources; its own local Git repository
pi/
  sessions/*.jsonl        # canonical pi session trees, messages, tools, image blocks
  transcript.md           # readable new user/assistant/tool events
  requests.json          # durable deduplication/interrupted-turn journal
  web-state.json         # bounded idle browser projection
  legacy-shared/         # imported pre-project web-agent sessions, if applicable
cad -> ../../cad/projects/<id>/cad
```

The CAD symlink works **on the host**. Its target has the project's database and
immutable artifacts. Storage is split across service mounts so the geometry service
does not receive transcripts/credentials and the agent does not receive a writable
CAD database. The link intentionally does not resolve inside the agent container.
For a portable full project backup, include/dereference its CAD target as well as
source and pi files; a plain tar without dereferencing will only capture the link.
New project folders and their host-side CAD link are materialized on catalog access.
The agent must use its scoped API, never the host-side link.

Provider credentials and login secrets stay in the existing global private stores,
**not in project folders**. Transcripts and generated runtime files stay outside
source Git repositories and images. JSONL is canonical; Markdown omits reasoning
blocks and binary image payloads and records visible events chronologically (not a
flattened replacement for pi's branch tree). The website serves only the readable
transcript, not arbitrary files or raw session JSONL. Protect/backup transcripts as
private operator data. This stores the web pi agent's transcript, not the separate
host coding-agent conversation.

## Project uploads

**Files → Project uploads** accepts one file and an optional note. Uploads belong to
 the project, not the viewed revision; they never advance the working model or
publication. Notes can be edited (4000 characters); concurrent stale edits are
rejected. Deleting an upload requires confirmation and does not affect CAD outputs.

Limits: 10 MiB per file, 512 MiB and 500 files per project. Content is stored as
opaque bytes under that project's CAD `uploads/` folder with random internal IDs;
metadata, SHA-256 and notes live in the additive `project_uploads` SQLite table.
Back up both the database and uploads folder. Files are never automatically opened,
executed, extracted, imported into CAD, or added to source Git. Treat uploaded
content and notes as untrusted reference data, not agent instructions. Avoid secrets.

Authenticated, project-prefixed routes:
- `GET /api/uploads`: list metadata and notes.
- `POST /api/uploads`: multipart `file` plus optional `note`.
- `PATCH /api/uploads/{id}`: JSON `{note, version}` (optimistic note update).
- `DELETE /api/uploads/{id}`: permanently delete only this uploaded asset.
- `GET|HEAD /downloads/uploads/{id}/file`: attachment-only download with byte ranges.

Browser mutations require the existing session CSRF token and same-origin checks.
Downloads remain authenticated and use octet-stream/nosniff, not inline HTML.
The agent can discover listing/download routes through CAD capabilities and inspect
reference files when requested; upload alone does not start an agent task.

## API and agent context

- `GET /api/projects`: catalog. `POST /api/projects` with `{name}`: create.
- `/projects/<id>/api/...`: state, schema, build, revision, validation,
  publish/restore, artifact and WebSocket contracts, scoped to that project.
- `POST /projects/<id>/api/workspace/commits`: append named/icon-labelled design change,
  using optimistic workspace generation and exact base revision; idempotent request key.
- `POST /projects/<id>/api/workspace/assets`: attach a named inspection/print/test output.
- `GET/HEAD /projects/<id>/downloads/sets/<asset>/<format>`: protected, meaningfully named
  downloads with range support. Registered outputs remain accessible beyond the latest
  100-build listing. No workspace mutations are exposed directly through the gateway.
- `/projects/<id>/downloads/...`: project-bound downloads.
- `/projects/<id>/api/agent/{state,prompt,abort,transcript}`: protected gateway routes.

Names never become filesystem paths; new IDs are generated. Browser selection is
URL-local, not a mutable global CAD selection. Each pi subprocess has an immutable
project-scoped `CAD_URL`, project source cwd and explicit session directory.
`SessionManager.continueRecent` resumes that project's latest session. Export URLs
retain the project prefix. The old unscoped API aliases the dripper for compatibility.
Requests cannot resolve another project's revisions through their current project.

There is one shared geometry semaphore and at most eight active/queued tasks globally;
the existing per-store queue bound also applies. Idempotency keys and publication
generations are project-local. Project creation never multiplies worker capacity.
The agent's built-in filesystem tools remain single-owner tools; these folders are
not security isolation from one another.

## Migration and rollback

`scripts/migrate-project-folders.py --runtime ...` is an **offline, copy-only**
migration for the existing dripper/B-01 installation. Stop the pod first. It checks
for active work, locks the CAD root, refuses existing destinations, takes SQLite
backups, checks integrity and verifies every copied artifact/session SHA-256.
Original storage, source workspace and agent sessions are retained unchanged.

- Dripper retains the complete original shared CAD history, including historical
  development candidates, and all 30 publication events/IDs.
- Bike basket twist-lock receives copies of the three B-01 candidates, no fabricated
  publications, generation 0, and its source files.
- Imported revision rows/artifact bytes are unchanged, including old parent IDs and
  base generations. Before publishing an imported B-01 candidate, rebuild its source
  against the new project's current generation with a new request key. Never rewrite
  its original base generation to force publication.
- Both folders archive the original **mixed shared** web-agent transcript, with hashes
  and provenance. It is not falsely split or automatically replayed as new context.
  New pi sessions start project-scoped. Source AGENTS files explain the migration.

The dripper's former default artifact URLs continue resolving the same bytes. If a
migration is interrupted between its two destination renames, complete the documented
staging rename before starting services; do not rerun or overwrite destinations.
Rollback uses the retained pre-project images and original data. Preserve all new
project data before rollback; older images do not know about post-migration work.
