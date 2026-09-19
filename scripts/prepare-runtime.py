#!/usr/bin/env python3
"""Copy existing CAD data into isolated persistent container storage. Never overwrite it."""

import argparse
import tempfile
import os
from pathlib import Path
import secrets
import shutil
import sqlite3
import subprocess

parser = argparse.ArgumentParser()
parser.add_argument("--runtime", type=Path, default=Path.home() / ".local/share/3d-pi")
parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parent.parent / "data")
args = parser.parse_args()
root = args.runtime.resolve()
source = args.source.resolve()
root.mkdir(parents=True, exist_ok=True, mode=0o700)
for name in ["cad", "agent", "secrets"]:
    (root / name).mkdir(exist_ok=True, mode=0o700)
destination = root / "cad"
if source == destination:
    raise SystemExit("Source and destination must differ")
if not (destination / "project.sqlite3").exists():
    staging = Path(tempfile.mkdtemp(prefix=".cad-import-", dir=root))
    with sqlite3.connect(f"file:{source / 'project.sqlite3'}?mode=ro", uri=True) as src:
        if src.execute(
            "SELECT count(*) FROM revisions WHERE status IN ('queued','building')"
        ).fetchone()[0]:
            raise SystemExit("Wait for active builds before taking a snapshot")
        with sqlite3.connect(staging / "project.sqlite3") as target:
            src.backup(target)
    (staging / "artifacts").mkdir(exist_ok=True)
    with sqlite3.connect(staging / "project.sqlite3") as db:
        revisions = [r[0] for r in db.execute("SELECT id FROM revisions")]
    for revision in revisions:
        if len(revision) != 32 or any(c not in "0123456789abcdef" for c in revision):
            raise SystemExit("Invalid stored revision id")
        path = source / "artifacts" / revision
        if path.exists():
            shutil.copytree(path, staging / "artifacts" / revision, dirs_exist_ok=True)
    destination.rmdir()  # Refuse to overwrite any pre-existing contents.
    staging.rename(destination)
    print(f"Copied {len(revisions)} revisions. Original data retained at {source}")
else:
    print("Existing runtime database retained; no overwrite performed.")
secret = root / "secrets/agent-token"
if not secret.exists():
    fd = os.open(secret, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as file:
        file.write(secrets.token_urlsafe(48))
workspace = root / "workspace"
if not workspace.exists():
    repo = Path(__file__).resolve().parent.parent
    subprocess.run(["git", "clone", "--no-hardlinks", str(repo), str(workspace)], check=True)
    subprocess.run(["git", "-C", str(workspace), "remote", "remove", "origin"], check=True)
    subprocess.run(
        ["git", "-C", str(workspace), "config", "user.name", "CAD Workspace"], check=True
    )
    subprocess.run(
        ["git", "-C", str(workspace), "config", "user.email", "cad-workspace@localhost"], check=True
    )
print(f"Persistent runtime prepared at {root}. Configure secrets/password.json before starting.")
