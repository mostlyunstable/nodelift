"""Built-in example workflows: JSON inside the package, so a bundled app finds them too."""

import json
from importlib import resources
from typing import Any


def load_examples() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for item in resources.files(__package__).iterdir():
        if item.name.endswith(".json"):
            data = json.loads(item.read_text(encoding="utf-8"))
            out[data["id"]] = data
    return out
