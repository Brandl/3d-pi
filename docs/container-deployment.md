# Install the authenticated alpha studio

This guide builds containers **locally from source**. There are no prebuilt
runtime releases. Dependencies retain their licences; read
[third-party notices](../THIRD_PARTY_NOTICES.md) before redistributing an image.

## Prerequisites and boundary

Use Linux, rootless Podman, Git, Node.js 24, uv and Python 3.12. Configure rootless
UID/GID mappings first. Allow room for native dependencies, build caches, CAD
artifacts and backups; resource limits do not prevent disk exhaustion. The
launcher sets memory ceilings of 8 GiB CAD, 2 GiB agent and 1 GiB web.

Use a committed source checkout. Preparation clones committed Git source, not
uncommitted edits. If starting with a source archive, first initialize its clean
contents as a local Git repository and commit them, before adding credentials or
runtime data. Independent-machine installation validation remains a release gate;
these recipes are not a claim of portability to every OS or container engine.

Three non-root containers share a rootless pod network:

| Service | Purpose | Writable persistent data |
| --- | --- | --- |
| CAD | Bounded geometry service and private API | CAD databases, artifacts, uploads, sections |
| Agent | Project-scoped pi worker and protected router | Sources, conversations, provider state |
| Web | Authenticated studio and allowlisted proxy | Hashed website login sessions |

The web service has no provider-credential or CAD-data mount. The agent has shell
and file tools; this is one trusted owner's workspace, not an untrusted-user
sandbox. Do not mount a container socket or the whole host home directory.

## 1. Prepare isolated initial data

For a new installation only; do not reuse or overwrite a live runtime:

```sh
uv sync --locked
(cd web && npm ci && npm run build)
uv run python -m cad.cli serve
```

In another terminal, run `uv run python -m cad.cli demo` to build/publish the
teaching model. Stop the local service after it completes. Then:

```sh
podman build -t localhost/3d-pi-cad:workspace -f Containerfile .
podman build -t localhost/3d-pi-agent:workspace -f agent/Containerfile .
python3 scripts/prepare-runtime.py --source "$PWD/data"
uv run python -m cad.auth "$HOME/.local/share/3d-pi/secrets/password.json"
```

Preparation copies the default CAD store using a SQLite backup and preserves
original artifacts. It refuses active builds and does not overwrite an existing
destination database. It is a bootstrap helper, **not** a complete multi-project
backup/import utility. Stop all writers first. A failed import can leave private
staging data; do not treat that directory as live state.

The default private runtime is `~/.local/share/3d-pi`. Keep secret files mode 0600
and directories private. Store the generated website password in a password
manager; never commit it, log it in CI or bake it into an image. The password
record is not a plaintext password.

## 2. Choose provider authentication

Set `PI_PROVIDER` and `PI_MODEL` to an actual supported provider/model available
to your account. Script defaults are not a promise of availability. Choose one
authentication owner, rather than duplicating rotating OAuth tokens:

- **Host-owned login:** set `PI_SEED_AUTH_FILE="$HOME/.pi/agent/auth.json"` when
  launching. Only that file is mounted read-only. The bridge refuses token writes
  and refresh callbacks. Renew on the host; if renewal replaces the file by
  rename, recreate the agent container while idle to pick up the new inode.
- **Container-owned login:** omit the seed. After launch, use
  `podman exec -it 3d-pi-agent pi`, then `/login`. Exit that interactive client
  before browser work. Its credentials persist in the mounted agent state.

Never expose provider credentials to the browser, source repository or geometry
worker. Provider/model changes and credential renewal may require an idle restart.

### Startup login check in the browser

The agent router checks local provider-credential metadata at startup and on each
authenticated state read, even before a project worker exists. The chat panel
shows the configured provider/model and server-terminal login instructions. It
distinguishes container-owned login from the read-only host bridge, unreadable
credentials, expired login and OAuth that Pi can attempt to renew on a request.
Use **Recheck Pi login** after setup; regular polling also notices changes.
A custom `CAD_POD` gets the matching agent-container command from the launcher.

This check never refreshes tokens, evaluates key commands, starts a model turn or
contacts a provider. “Available locally” is **not** proof of remote authentication,
subscription/model entitlement or billing. Ambient/custom authentication remains
unverified; absent stored credentials alone do not block these other providers.
A missing default Codex login, missing host-bridge login or unreadable/expired
credentials disables new sends, but never Stop. Drafts and uncertain receipts are
preserved and are not automatically sent when login becomes available.

An unreachable agent is shown separately from a missing login. Website login and
provider login are independent; neither website logout nor this status check
revokes provider credentials. Never paste authorization codes or keys into chat.

## 3. Launch and expose only the gateway

With the chosen `PI_PROVIDER`, `PI_MODEL` and optional `PI_SEED_AUTH_FILE` exported:

```sh
scripts/run-podman.sh
podman healthcheck run 3d-pi-cad
podman healthcheck run 3d-pi-web
podman healthcheck run 3d-pi-agent
```

The launcher refuses an existing pod; it is not an in-place upgrade command.
Default host ports are loopback 8765 (private CAD) and 8767 (web gateway). Agent
ports are internal to the pod. Never expose the CAD API or agent bridge publicly.
Put **only the web gateway behind HTTPS**, using a reverse proxy or tunnel you
control. Secure cookies must not be worked around by disabling authentication.

Log in through the HTTPS gateway. Select/create a project and ask for a small
model, inspection and an explicit saved design without publication. Verify live
intermediaries, saved history, named downloads, logout denial and restart recovery.
Check actual downloaded file contents, not just successful HTTP status codes.

For a separate staging installation, use `CAD_RUNTIME_DIR`, `CAD_POD`,
`CAD_API_PORT` and `CAD_WEB_PORT`; pass the same runtime path to preparation and
password creation. Never share writable runtime directories with production.
Stable DNS, HTTPS renewal and host-boot supervision are operator responsibilities.

## Sessions and interruptions

Website sessions have a 365-day inactivity lifetime with at-most-daily renewal.
Only token hashes are persisted. Logout revokes a session; changing password
configuration and restarting revokes stored sessions. Use a trusted device and
protect the login database as private state.

Chat drafts/uncertain receipts live in per-project, per-tab session storage and
are cleared on logout. Provider credentials do not live there. The agent has a
15-minute no-progress timeout and a one-hour absolute bound. Stop/timeout/provider
failure is not rollback. Inspect existing source and CAD changes before continuing;
very old uncertain requests must not be blindly replayed.

## Upgrade, backup and recover

1. Wait for agent turns and CAD builds to finish; check idleness again immediately
   before replacement. Back up first and record source/image versions.
2. Close the public entry point during replacement. Keep previous images/containers
   available for rollback. Source edits do not hot-reload installed services.
3. Verify saved heads, history, outputs and pre-existing authentication before
   reopening access. Restart policy alone is not a boot-supervision plan.

For complete backups, stop writers or coordinate SQLite online backups with
consistent artifact, upload, source-Git and session snapshots. Include each
project's CAD symlink target. Store encrypted off-machine copies; protect provider
credentials separately. Backing up only the default database is insufficient.

Preserve newer data before rollback. Confirm old code understands the current
schema; never reset history, discard new artifacts or restore an anonymous gateway
as a shortcut. See [project storage](projects.md) and [security](../SECURITY.md).

Mutation-heavy browser/tool tests belong on isolated data and ports. Authenticated
browser traces, logs and storage exports may contain secrets and must stay private.
