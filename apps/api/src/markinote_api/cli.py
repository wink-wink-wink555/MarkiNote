"""Command line entry point."""
from __future__ import annotations

import os

import uvicorn


def main() -> None:
    uvicorn.run(
        "markinote_api.application:app",
        host=os.getenv("MARKINOTE_HOST", "127.0.0.1"),
        port=int(os.getenv("MARKINOTE_PORT", "8000")),
        reload=os.getenv("MARKINOTE_RELOAD", "").lower() in {"1", "true", "yes"},
        factory=False,
        access_log=False,
    )
