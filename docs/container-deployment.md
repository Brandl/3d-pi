# Password-protected CAD + pi workspace

## Scope and boundaries

One trusted owner, one CAD design history and one persistent pi conversation. The browser can view earlier publications without changing the active model. Chat prompts are commands to an agent with CAD, shell and file tools; do not share this password with untrusted people. Separate projects/designs and fine-grained accounts are not implemented yet.

Three non-root containers share a rootless Podman pod's network:

- `3d-pi-cad`: private modeling API / bounded geometry worker, persistent `/data`. No provider credentials.
- `3d-pi-agent`: pi SDK 0.85.1, CAD extension and command/file tools. Persistent `/workspace` Git checkout and `/agent-state` sessions/request journal. Internal bearer-authenticated bridge on loopback port 8768; not host-published.
- `3d-pi-web`: viewer, login and allowlisted agent proxy. Only password hash and internal bridge token mounted; no provider credentials or direct data mount.

Host API and gateway ports bind **127.0.0.1 only**. Tunnel only the gateway through HTTPS. Do not publish the API or agent bridge. Containers have read-only root filesystems, writable temporary storage, dropped capabilities, no-new-privileges, PID/CPU/memory limits and no host/Podman socket. This is not a multi-tenant security sandbox; writable persistent volumes have no disk quota.

Python/npm dependencies are locked and base images are digest-pinned. OS packages still come from their distribution repositories, so record built image IDs with each deployment; builds are not claimed bit-for-bit reproducible. Native runtime libraries include OpenGL, OpenMP, Kerberos error and PKCS#11 libraries needed by MeshLab. The image build context excludes runtime data, credentials, Git history and dependencies; COPY statements also whitelist source directories.

## Build and prepare (do not overwrite an existing runtime)

```sh
podman build -t localhost/3d-pi-cad:workspace -f Containerfile .
podman build -t localhost/3d-pi-agent:workspace -f agent/Containerfile .
python3 scripts/prepare-runtime.py --source "$PWD/data"
.venv/bin/python -m cad.auth "$HOME/.local/share/3d-pi/secrets/password.json"
```

The preparation script takes a SQLite backup and copies immutable artifacts into a separate directory, then creates a local Git clone without a remote. Quiesce publications/builds while taking the snapshot. It refuses active builds and never overwrites an existing destination database. The original `data/` remains untouched. A failed import may leave a private `.cad-import-*` staging directory for inspection; it is not selected as live data.

Default persistent root: `~/.local/share/3d-pi`:

- `cad/project.sqlite3`, `cad/artifacts/`
- `workspace/` (source Git, not a hot-reloaded application installation)
- `agent/sessions/`, `agent/requests.json`, `agent/pi/`, `agent/models-store.json`
- `secrets/password.json` (scrypt hash), `secrets/agent-token` (internal random bearer token)

Keep the root private and secrets mode 0600. No plaintext website password needs to be retained. `cad.auth --generate` prints a generated password once; store it in your password manager. Never commit secrets or sessions.

## Provider login

Two modes:

1. **Existing host login, read-only bridge** (initial deployment): pass `PI_SEED_AUTH_FILE="$HOME/.pi/agent/auth.json"`. Only this file is mounted read-only, not the entire host pi directory. A credential-store adapter reads the selected provider and refuses all write/refresh callbacks. The host remains the sole OAuth refresh owner. Renew an expired login on the host; the agent rereads it before turns. If replacing the file by rename rather than writing in place, recreate the agent container so the file bind mount points at the new inode.
2. **Dedicated container login:** omit the seed. Run `podman exec -it 3d-pi-agent pi`, use `/login`, and exit the interactive process before web work. `PI_CODING_AGENT_DIR=/agent-state/pi` persists that login. Do not initialize this mode by duplicating a rotating refresh token owned by another active client. The web SDK uses the same auth file; after login, restart the agent if necessary.

`PI_PROVIDER` and `PI_MODEL` select the model (initially `openai-codex` / `gpt-6-astra`). A model must exist in the SDK catalog. A non-secret host `models-store.json` may be copied into `agent/models-store.json` for a catalog model not in the bundled list. Never bake provider auth into an image or pass provider tokens through the browser.

## Stage, verify, then cut over

```sh
CAD_POD=3d-pi-stage CAD_API_PORT=8875 CAD_WEB_PORT=8877 \
PI_SEED_AUTH_FILE="$HOME/.pi/agent/auth.json" scripts/run-podman.sh
```

`CAD_RUNTIME_DIR` overrides the persistent root. Never run staging and live services against the same writable root simultaneously. Verify login, anonymous denials, downloads/checksums, a real pi tool call, a candidate geometry build without publication, and a pod restart. Original revision IDs and published history must remain intact.

Stop the public tunnel before stopping/replacing the old services. Stop/remove the staging pod (not its persistent directories), stop old host services to free ports, then:

```sh
PI_SEED_AUTH_FILE="$HOME/.pi/agent/auth.json" scripts/run-podman.sh
# Check localhost:8767 denies anonymous access before opening a tunnel.
cloudflared tunnel --url http://127.0.0.1:8767
```

Quick Tunnel addresses are temporary. Use HTTPS and log in. Public downloads now require the same session; old anonymous links no longer grant access. The gateway offers no public CAD mutations/source: authenticated agent prompts are the only browser editing path.

## Operations

```sh
podman pod stop 3d-pi
podman pod start 3d-pi
podman logs --tail 100 3d-pi-agent
podman healthcheck run 3d-pi-cad
podman healthcheck run 3d-pi-web
podman healthcheck run 3d-pi-agent
```

Restart policies cover container failures; automatic host-boot startup/Quadlet and a stable tunnel/domain are separate follow-up work. Do not claim reboot persistence of the running service merely because its files persist.

Website sessions expire after eight hours; logout invalidates the session. A gateway restart invalidates all website sessions. Password login is throttled and password hashes are checked serially; authenticated mutations require Origin + CSRF validation. All protected responses are no-store. A stopped/restarted agent preserves conversation and request IDs; an interrupted request is marked interrupted and is never automatically replayed. Only one turn is accepted at a time; repeated request IDs are deduplicated. Stop aborts the turn. A 15-minute turn limit also requests abort. Aborting does **not** roll back already executed CAD publications or file changes; inspect current state before retrying.

To change the website password, run `cad.auth` on the existing hash path and restart the web container. Keep that hash path's permissions private. Do not change it while expecting old sessions to remain valid.

For upgrades, finish/stop agent work and CAD builds, back up the runtime, checkpoint source Git, rebuild images, stop/remove the pod, and rerun the deployment script. The script refuses to replace an existing pod implicitly. Application changes in the agent's `/workspace` require an explicit image rebuild/deployment; they do not hot-reload the running services.

## Backup and rollback

Stop all writers for a full backup, or combine a SQLite online backup with an immutable artifact copy and consistent session/source snapshots. Back up CAD data, agent state and workspace Git separately from secrets. Encrypt backups that include conversations or credentials. A local Git repository is not an off-machine backup; no remote is configured automatically.

The initial migration retains the original repository's `data/` as a rollback copy. Before any rollback, preserve the newer container runtime too: switching back discards newer live changes from view unless they are explicitly reconciled. Never `git reset` or overwrite runtime data as a substitute for migration.

To roll back the runtime, stop the tunnel and container pod, start the original CAD service against its original data, and run the **password-protected** gateway with `CAD_PASSWORD_HASH_FILE` configured. Verify anonymous access is blocked before retunneling. Do not restore the old anonymous public gateway.

## Initial deployment verification

At source checkpoint `49613c8`, staging used a separate copy on ports 8875/8877 before cutover to 8765/8767. All 30 publications, 32 original build records and 712 artifact files were preserved; every copied artifact matched byte-for-byte. A fresh, unpublished container build of generation 30's Origami document passed validation and produced five STL files identical to the published originals. Published generation 30 was not changed.

A real containerized pi turn called `cad_inspect` successfully. Conversation/request state survived container recreation. Login/logout and protected chat were checked in a real browser; all five public HTTPS Playwright tests passed, including timeline browsing, historical downloads and PNG/WebGL fallbacks. Backend: 91 tests; agent bridge/credentials: four tests. All three container health checks passed. Initial built image IDs: CAD `55ab01cff1bf`, agent `1138c66f5af6`.

### Workbench UI update

Source checkpoint `d93b44b` adds the CAD command ribbon/model browser/bottom timeline and component reference UI. Only the web container was replaced (image `2f8edd7f08c0`); the running CAD and pi containers were left intact. Seven public HTTPS browser tests passed, covering login/logout, desktop/mobile library drafts, timeline browsing, downloads and WebGL/PNG views. The library is a bundled reference catalog with explicit chat drafts, not automatic component instantiation. The previous web image is retained as `localhost/3d-pi-cad:before-workbench` for rollback.

### Refined CAD tools and shared tree

Source checkpoint `3264927` upgrades the API, gateway and persistent pi agent together. Fifteen CAD tools expose live limits, revision/feature/part/interface trees, component inspection, focused diagnostics and explicit cancellation/idempotent retries. The model browser consumes the same tree endpoints. No geometry was published by the upgrade; all pre-upgrade stored state was checked unchanged. The real web agent successfully called capabilities, inspect and tree in a read-only smoke turn.

Verification: 97 backend tests, four bridge/credential tests, the actual pi loader integration exercising all 15 CAD tools against isolated data, and eight public HTTPS browser tests passed. Prior images are retained as `localhost/3d-pi-{cad,web,agent}:before-tool-refinement`. See [tool contracts](agent-tools.md) for semantics and limitations.

### Automatic visual checkpoints

Source `1053c1f` adds automatic multi-view image tool results, separate named-colour review PNGs, legacy-image fallback, bounded delivery, compaction reset and an explicit pause for unseen publish/restore checkpoints. `fdcc09c` caps closer inspection framing using projected vertices so bulky assemblies remain inside the viewport. See [visual-review semantics](visual-review.md); hidden-line/dotted occlusion rendering is still planned.

The real persistent agent received four image blocks from a default `cad_inspect` call and described the visible assembly without building or publishing. Its saved tool result was checked for all four actual images. Full backend suite: 99 tests passed before the framing follow-up; nine targeted rendering/geometry tests passed afterward, including projected-cube containment. The actual pi-loader integration covers automatic images, compaction reset, pre-publication pausing, legacy fallback and missing-image handling. Pre-upgrade CAD state remained unchanged. Prior service images are retained under `:before-visual-checkpoints`.

### Folder-project rollout

`ff31111` introduced [folder projects](projects.md); `46252ae` additionally hardens cancelled transcript downloads. The live copy-only migration preserved all **39 original revision records and 30 publications**, all copied artifact bytes, and the original runtime/agent session files. Dripper remains generation 30; Bike basket twist-lock has three imported unpublished candidates and generation 0. Both projects retain hashed, explicitly shared legacy web-pi transcripts. New source repositories and canonical pi JSONL sessions are separate.

Validation: 102 backend tests, six agent tests, the real 15-tool loader integration against an isolated project-scoped endpoint, and two isolated local-browser project tests passed. Real production-browser read-only turns used different project session IDs, received four dripper / three bike image blocks, and reported correct scoped CAD state. The bike conversation resumed with the same session ID and previous messages after an agent-container restart. Local desktop/mobile checks found no browser errors or horizontal page overflow. Verification did not build or publish anything. Prior service images remain tagged `:before-projects`; original root data remains available for rollback. Read the migration/rollback notes before using those older images.

## Validation commands

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python -m pytest -q
.venv/bin/ruff check cad tests scripts/prepare-runtime.py
(cd agent && npm test)
(cd web && npm run build)
# Authenticated browser storage state is a secret: use a private temporary path.
(cd web && CAD_URL=https://your-gateway CAD_BROWSER_AUTH=/private/browser-state.json \
  npx playwright test tests/timeline.spec.ts tests/casting-box.spec.ts)
```

Do not commit browser storage state, traces containing secrets, or provider logs with credentials.
