"""Local development CLI. Browser and pi use the same service API."""

import argparse
import json
import os
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path


def api(path, data=None, base=None):
    base = base or os.environ.get("CAD_URL", "http://127.0.0.1:8765")
    request = urllib.request.Request(
        base + path,
        data=json.dumps(data).encode() if data is not None else None,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(exc.read().decode()) from exc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve")
    serve.add_argument("--port", type=int, default=8765)
    sub.add_parser("demo", help="Build and publish the enclosure example")
    sub.add_parser("inspect")
    build = sub.add_parser("build")
    build.add_argument("document", type=Path)
    build.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    if args.command == "serve":
        import uvicorn

        uvicorn.run("cad.app:create_app", factory=True, host="127.0.0.1", port=args.port)
        return
    state = api("/api/state")
    if args.command == "inspect":
        print(json.dumps(state, indent=2))
        return
    doc = (
        api("/api/example")
        if args.command == "demo"
        else json.loads(args.document.read_text(encoding="utf-8"))
    )
    row = api(
        "/api/builds",
        {
            "document": doc,
            "expected_generation": state["generation"],
            "request_key": uuid.uuid4().hex,
        },
    )
    print(f"Building {row['id']}…", flush=True)
    deadline = time.monotonic() + 120
    while row["status"] in ("queued", "building") and time.monotonic() < deadline:
        time.sleep(0.3)
        row = api(f"/api/revisions/{row['id']}")
    print(json.dumps({"id": row["id"], "status": row["status"], "result": row["result"]}, indent=2))
    if row["status"] != "ready" or not row["result"]["report"]["valid"]:
        raise SystemExit("Build failed or checks did not pass; published model unchanged")
    if args.command == "demo" or args.publish:
        api(f"/api/revisions/{row['id']}/publish", {"expected_generation": state["generation"]})
        print(f"Published. Open {os.environ.get('CAD_URL', 'http://127.0.0.1:8765')}")


if __name__ == "__main__":
    main()
