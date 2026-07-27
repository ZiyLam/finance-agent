"""Convenience command for local API development."""

from __future__ import annotations

from os import getenv

import uvicorn

from .main import app


def main() -> None:
    """Start one development API process; production uses an external process manager."""

    uvicorn.run(
        app,
        host=getenv("AGENT_API_HOST", "127.0.0.1"),
        port=int(getenv("AGENT_API_PORT", "8000")),
        log_level=getenv("AGENT_API_LOG_LEVEL", "info"),
    )


if __name__ == "__main__":
    main()
