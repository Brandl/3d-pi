"""One build per process. Limits contain accidents; this is NOT an OS sandbox."""

import json
import resource
import sys
import time
from pathlib import Path


def main():
    directory = Path(sys.argv[1]).resolve()
    resource.setrlimit(resource.RLIMIT_CPU, (75, 80))
    resource.setrlimit(resource.RLIMIT_AS, (6 * 1024**3, 6 * 1024**3))
    resource.setrlimit(resource.RLIMIT_FSIZE, (128 * 1024**2, 128 * 1024**2))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    start = time.monotonic()
    try:
        from cad.geometry import build_artifacts
        from cad.schema import Document

        doc = Document.model_validate_json(
            (directory / "document.json").read_text(encoding="utf-8")
        )
        result = {"status": "ready", **build_artifacts(doc, directory)}
    except Exception as exc:
        result = {"status": "failed", "error": str(exc)[:4000]}
    result["duration_seconds"] = round(time.monotonic() - start, 3)
    (directory / "result.json").write_text(json.dumps(result, allow_nan=False))


if __name__ == "__main__":
    main()
