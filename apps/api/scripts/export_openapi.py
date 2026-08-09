"""Export the canonical OpenAPI contract used by the TypeScript client.

The output is deterministic so CI can fail on an unreviewed contract drift.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
API_SOURCE = REPOSITORY_ROOT / "apps" / "api" / "src"
DEFAULT_OUTPUT = REPOSITORY_ROOT / "packages" / "api-client" / "openapi.json"


def export_openapi(output: Path = DEFAULT_OUTPUT) -> Path:
    sys.path.insert(0, str(REPOSITORY_ROOT))
    sys.path.insert(0, str(API_SOURCE))

    from markinote_api.application import app

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(app.openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output


if __name__ == "__main__":
    destination = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else DEFAULT_OUTPUT
    print(export_openapi(destination))
