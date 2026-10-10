"""Optional historical regression inputs, deliberately excluded from public source."""

import json
from pathlib import Path

import pytest


def load_local_example(name):
    filename = name if name.endswith(".json") else name + ".json"
    path = Path(__file__).resolve().parent.parent / "examples" / filename
    if not path.is_file():
        pytest.skip(f"Optional local design fixture is not distributed: {filename}")
    return json.loads(path.read_text(encoding="utf-8"))
