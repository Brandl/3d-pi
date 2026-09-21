#!/usr/bin/env python3
"""Explicit, repeatable registration of existing geometry. Never build or publish.

Manifest: {revision, name, icon, source_file, assets:[{revision,role,name,note}]}.
Use only after reviewing role assignments. Existing source/artifacts stay unchanged.
"""

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import httpx

p = argparse.ArgumentParser(description=__doc__)
p.add_argument("--api", default="http://127.0.0.1:8765")
p.add_argument("--project", required=True)
p.add_argument("--source", required=True, type=Path)
p.add_argument("--manifest", required=True, type=Path)
a = p.parse_args()
url = urlparse(a.api)
if url.scheme != "http" or url.hostname not in ("localhost", "127.0.0.1", "::1"):
    p.error("Use the private loopback CAD API")
if not a.project or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in a.project):
    p.error("Invalid project ID")
manifest = json.loads(a.manifest.read_text())


def git(*args):
    return subprocess.check_output(["git", "-C", str(a.source), *args], text=True).strip()


if git("status", "--porcelain", "--untracked-files=no"):
    p.error("Source repository has uncommitted tracked changes")
source_commit = git("rev-parse", "HEAD")
source_file = manifest["source_file"]
if source_file.startswith("/") or any(c in ("", ".", "..") for c in source_file.split("/")):
    p.error("Use a tracked relative source file")
document = json.loads(git("show", f"{source_commit}:{source_file}"))
client = httpx.Client(base_url=a.api.rstrip("/") + f"/projects/{a.project}", timeout=30)


def get():
    r = client.get("/api/state")
    r.raise_for_status()
    return r.json()


def post(path, data):
    r = client.post(path, json=data)
    r.raise_for_status()
    return r.json()


def key(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


before = get()
workspace = before["workspace"]
existing = next(
    (
        c
        for c in workspace["commits"]
        if c["revision"] == manifest["revision"]
        and c["source_commit"] == source_commit
        and c["name"] == manifest["name"]
        and c["icon"] == manifest["icon"]
    ),
    None,
)
if existing:
    committed = existing
else:
    payload = dict(
        revision=manifest["revision"],
        name=manifest["name"],
        icon=manifest["icon"],
        expected_generation=workspace["generation"],
        base_revision=workspace["revision"] or before["revision"],
        source_file=source_file,
        source_commit=source_commit,
        source_document=document,
    )
    payload["request_key"] = key(payload)
    committed = post("/api/workspace/commits", payload)
for asset in manifest.get("assets", []):
    payload = dict(asset, commit=committed["id"])
    payload["request_key"] = key(payload)
    post("/api/workspace/assets", payload)
after = get()
assert before["revision"] == after["revision"] and before["generation"] == after["generation"]
assert before["publications"] == after["publications"]
print(
    json.dumps(
        {
            "commit": committed["id"],
            "name": committed["name"],
            "icon": committed["icon"],
            "workspace_generation": after["workspace"]["generation"],
            "publication_generation": after["generation"],
            "assets": len(after["workspace"]["assets"]),
            "geometry_changed": False,
        },
        indent=2,
    )
)
