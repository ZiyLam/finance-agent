"""Persistent, non-secret enablement choices for external providers."""

from __future__ import annotations

import json
from os import getenv, replace
from pathlib import Path
from threading import RLock
from uuid import uuid4

from .data_sources import get_data_source


class ProviderActivationError(RuntimeError):
    """A safe local-settings failure without provider credentials or payloads."""


def default_provider_settings_path() -> Path:
    """Keep mutable user choices outside the repository and its Git tree."""

    local_data = Path(getenv("LOCALAPPDATA", r"C:\Users\Default\AppData\Local"))
    return local_data / "Codex" / "finance-agent" / "provider-settings.json"


class ProviderActivationStore:
    """Persist explicit provider enable/disable choices for the current user.

    Existing providers default to their catalog value so upgrading does not
    silently disable a working setup. Every runtime check rereads this small
    file, allowing a settings-page toggle to affect cached Agent/tool objects.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or default_provider_settings_path()
        self._lock = RLock()

    def is_enabled(self, source: str) -> bool:
        definition = get_data_source(source)
        if definition is None:
            raise ValueError("Unknown provider")
        with self._lock:
            overrides = self._read()
        return overrides.get(definition.name, definition.enabled_by_default)

    def set_enabled(self, source: str, enabled: bool) -> bool:
        definition = get_data_source(source)
        if definition is None:
            raise ValueError("Unknown provider")
        if not isinstance(enabled, bool):
            raise ValueError("Provider enabled state must be boolean")
        with self._lock:
            overrides = self._read()
            overrides[definition.name] = enabled
            self._write(overrides)
        return enabled

    def _read(self) -> dict[str, bool]:
        if not self._path.exists():
            return {}
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ProviderActivationError("Provider settings could not be read") from error
        enabled = payload.get("enabled") if isinstance(payload, dict) else None
        if not isinstance(enabled, dict) or not all(
            isinstance(name, str) and isinstance(value, bool)
            for name, value in enabled.items()
        ):
            raise ProviderActivationError("Provider settings have an invalid format")
        return dict(enabled)

    def _write(self, enabled: dict[str, bool]) -> None:
        temporary_path = self._path.with_name(f"{self._path.name}.{uuid4().hex}.tmp")
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path.write_text(
                json.dumps({"version": 1, "enabled": enabled}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            replace(temporary_path, self._path)
        except OSError as error:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise ProviderActivationError("Provider settings could not be saved") from error
