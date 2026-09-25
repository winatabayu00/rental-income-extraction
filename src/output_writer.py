"""Write machine-readable JSON output."""
from __future__ import annotations

import json
import os
from typing import Any, Dict


def write_results(payload: Dict[str, Any], output_dir: str) -> str:
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "results.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    return path
