"""Export the backend contract without starting a server or mounting Web assets."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from ai_agent.api.app import create_app, create_development_components


def openapi_json() -> str:
    components = create_development_components(
        session_secret="openapi-export-only-session-secret",
    )
    app = create_app(
        components,
        serve_web=False,
        web_allowed_origins=(),
    )
    return json.dumps(app.openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Export the Finance Agent OpenAPI contract.")
    parser.add_argument("--output", type=Path, help="Write JSON to this file instead of standard output.")
    arguments = parser.parse_args()
    document = openapi_json()
    if arguments.output is None:
        sys.stdout.write(document)
        return

    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(document, encoding="utf-8")
    print(f"OpenAPI contract written to {arguments.output}")


if __name__ == "__main__":
    main()
