"""Bounded, derived inspection cache, separate from immutable build artifacts."""

import asyncio
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

from fastapi import HTTPException

from cad.sections import FILES, VERSION

MAX_SECTION_BYTES = 16 * 1024**2
MAX_CACHE_BYTES = 256 * 1024**2
MAX_PER_REVISION = 64


def cache_root(store, revision):
    return store.directory(revision).parent.parent / "sections"


def recover_pending(store):
    # Called only at service startup, with the exclusive service lock held.
    root = store.root / "sections"
    if root.exists():
        for path in root.glob(".pending-*"):
            if path.is_dir():
                shutil.rmtree(path)


def section_file(store, revision, section_id, filename):
    store.get(revision)  # Resolve in the current project before accessing any path.
    if not re.fullmatch(r"[a-f0-9]{64}", section_id) or filename not in FILES:
        raise HTTPException(404, "Unknown section artifact")
    directory = cache_root(store, revision) / revision / section_id
    if not (directory / "summary.json").is_file() or not (directory / filename).is_file():
        raise HTTPException(404, "Section unavailable; generate it with cad_section first")
    return directory / filename


async def generate(store, revision, parameters, semaphore):
    row = store.get(revision)
    if row["status"] != "ready":
        raise HTTPException(409, "Section requires a ready immutable revision")
    step = row["result"]["exports"].get("step")
    if not step:
        raise HTTPException(
            422,
            "Exact sections require a STEP export. Mesh-only models are unsupported; no silent mesh approximation.",
        )
    if Path(step).name != step:
        raise HTTPException(422, "Invalid STEP export path")
    parameters = parameters.model_copy(
        update={"parts": sorted(set(parameters.parts)) if parameters.parts else None}
    )
    payload = {
        "version": VERSION,
        "revision": revision,
        "parameters": parameters.model_dump(mode="json"),
    }
    section_id = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    root = cache_root(store, revision)
    directory = root / revision / section_id

    def result(cached):
        return {
            **json.loads((directory / "summary.json").read_text()),
            "section_id": section_id,
            "cached": cached,
        }

    if (directory / "summary.json").is_file():
        return result(True)
    # No unbounded request/process queue alongside the bounded build worker.
    if semaphore.locked():
        raise HTTPException(429, "Geometry worker busy; retry this identical section later")
    async with semaphore:
        directory.parent.mkdir(parents=True, exist_ok=True)
        if len(list(directory.parent.iterdir())) >= MAX_PER_REVISION:
            raise HTTPException(
                409,
                "Section cache limit reached for this revision (64); existing sections remain available",
            )
        size = sum(p.stat().st_size for p in root.rglob("*") if p.is_file())
        if size + MAX_SECTION_BYTES > MAX_CACHE_BYTES:
            raise HTTPException(409, "Project section cache quota reached (256 MiB)")
        temp = Path(tempfile.mkdtemp(prefix=".pending-", dir=root))
        proc = None
        try:
            (temp / "input.json").write_text(
                json.dumps(
                    {
                        **payload,
                        "step": str(store.directory(revision) / step),
                        "measurements": row["result"]["report"]["parts"],
                    }
                )
            )
            env = {
                "PATH": os.path.dirname(sys.executable) + ":/usr/bin:/bin",
                "HOME": str(temp),
                "MPLCONFIGDIR": str(temp / ".mpl"),
                "PYTHONPATH": str(Path(__file__).resolve().parent.parent),
                "OPENBLAS_NUM_THREADS": "1",
                "OMP_NUM_THREADS": "1",
                "LANG": "C.UTF-8",
            }
            with (temp / "worker.log").open("wb") as log:
                proc = await asyncio.create_subprocess_exec(
                    sys.executable,
                    "-m",
                    "cad.sections",
                    str(temp),
                    cwd=temp,
                    env=env,
                    stdout=log,
                    stderr=log,
                )
                try:
                    await asyncio.wait_for(proc.wait(), timeout=50)
                except TimeoutError:
                    raise HTTPException(422, "Section exceeded 50-second worker deadline") from None
            if proc.returncode != 0 or not (temp / "summary.json").is_file():
                error = (
                    json.loads((temp / "error.json").read_text())["error"]
                    if (temp / "error.json").exists()
                    else "Section worker failed or exceeded resource limits"
                )
                raise HTTPException(422, error)
            outputs = FILES | {"summary.json"}
            if sum((temp / f).stat().st_size for f in outputs) > MAX_SECTION_BYTES:
                raise HTTPException(422, "Section output exceeds 16 MiB limit")
            # Remove scratch data before atomically exposing a complete cache entry.
            for child in temp.iterdir():
                if child.name not in outputs:
                    shutil.rmtree(child) if child.is_dir() else child.unlink()
            temp.rename(directory)
            return result(False)
        finally:
            if proc is not None and proc.returncode is None:
                proc.kill()
                await proc.wait()
            if temp.exists():
                shutil.rmtree(temp)
