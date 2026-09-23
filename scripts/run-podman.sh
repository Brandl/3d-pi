#!/usr/bin/env bash
set -euo pipefail
runtime="${CAD_RUNTIME_DIR:-$HOME/.local/share/3d-pi}"
pod="${CAD_POD:-3d-pi}"
api_port="${CAD_API_PORT:-8765}"
web_port="${CAD_WEB_PORT:-8767}"
for file in "$runtime/secrets/password.json" "$runtime/secrets/agent-token" "$runtime/cad/project.sqlite3"; do
  test -f "$file" || { echo "Missing $file; run prepare-runtime.py and configure a password first." >&2; exit 1; }
done
if podman pod exists "$pod"; then echo "Pod $pod already exists. Stop/remove that pod explicitly before redeploying; persistent data is separate." >&2; exit 1; fi
mkdir -p "$runtime/projects" "$runtime/web-auth"
chmod 700 "$runtime/projects" "$runtime/web-auth"
podman pod create --name "$pod" --userns=keep-id -p "127.0.0.1:$api_port:8765" -p "127.0.0.1:$web_port:8767"
common=(--pod "$pod" --read-only --cap-drop=ALL --security-opt=no-new-privileges --pids-limit=256 --tmpfs /tmp:rw,nosuid,nodev,size=256m --restart=unless-stopped)
podman run -d "${common[@]}" --name "$pod-cad" --memory=8g --memory-swap=8g --cpus=2 \
  -v "$runtime/cad:/data:rw" \
  --health-cmd "python -c 'import urllib.request; urllib.request.urlopen(\"http://127.0.0.1:8765/api/state\",timeout=5)'" \
  --health-interval=30s --health-start-period=30s localhost/3d-pi-cad:workspace
seed=()
if [[ -n "${PI_SEED_AUTH_FILE:-}" ]]; then
  test -f "$PI_SEED_AUTH_FILE"
  seed=(-v "$PI_SEED_AUTH_FILE:/run/secrets/pi-auth.json:ro" -e PI_SEED_AUTH_FILE=/run/secrets/pi-auth.json)
fi
podman run -d "${common[@]}" --name "$pod-agent" --memory=2g --memory-swap=2g --cpus=2 \
  -v "$runtime/agent:/agent-state:rw" -v "$runtime/workspace:/workspace:rw" \
  -v "$runtime/projects:/projects:rw" \
  -v "$runtime/secrets/agent-token:/run/secrets/agent-token:ro" \
  -e CAD_AGENT_TOKEN_FILE=/run/secrets/agent-token \
  -e "PI_PROVIDER=${PI_PROVIDER:-openai-codex}" -e "PI_MODEL=${PI_MODEL:-gpt-6-astra}" \
  --health-cmd "node /opt/agent/health.mjs" --health-interval=30s --health-start-period=30s \
  "${seed[@]}" localhost/3d-pi-agent:workspace
podman run -d "${common[@]}" --name "$pod-web" --memory=1g --memory-swap=1g --cpus=1 \
  -v "$runtime/web-auth:/auth-state:rw" -e CAD_SESSION_DB=/auth-state/sessions.sqlite3 \
  -v "$runtime/secrets/password.json:/run/secrets/password.json:ro" \
  -v "$runtime/secrets/agent-token:/run/secrets/agent-token:ro" \
  -e CAD_PASSWORD_HASH_FILE=/run/secrets/password.json -e CAD_AGENT_TOKEN_FILE=/run/secrets/agent-token \
  --health-cmd "python -c 'import urllib.request; urllib.request.urlopen(\"http://127.0.0.1:8767/auth/login\",timeout=5)'" \
  --health-interval=30s --health-start-period=30s \
  localhost/3d-pi-cad:workspace python -m uvicorn cad.preview:app --host 0.0.0.0 --port 8767
printf 'Private CAD: http://127.0.0.1:%s\nPassword-protected gateway: http://127.0.0.1:%s (publish only this gateway through HTTPS)\n' "$api_port" "$web_port"
