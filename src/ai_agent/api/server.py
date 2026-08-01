"""Convenience command for local API development."""

from __future__ import annotations

from os import getenv

import uvicorn

from ..observability import configure_server_logging, log_event
from .main import app


def main() -> None:
    """Start one development API process; production uses an external process manager."""

    log_path = configure_server_logging()
    log_event(
        "api_server_starting",
        host=getenv("AGENT_API_HOST", "127.0.0.1"),
        port=int(getenv("AGENT_API_PORT", "8000")),
        file_logging_enabled=log_path is not None,
    )
    uvicorn.run(
        app,
        host=getenv("AGENT_API_HOST", "127.0.0.1"),
        port=int(getenv("AGENT_API_PORT", "8000")),
        log_level=getenv("AGENT_API_LOG_LEVEL", "info"),
    )


if __name__ == "__main__":
    main()
