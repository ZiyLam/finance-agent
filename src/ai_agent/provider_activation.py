"""Persistent, non-secret enablement choices for external providers."""

from __future__ import annotations

import json
import os
from os import getenv, replace
from pathlib import Path
from threading import RLock
from uuid import uuid4

from .data_sources import get_data_source


class ProviderActivationError(RuntimeError):
    """A safe local-settings failure without provider credentials or payloads."""


def default_provider_settings_path() -> Path:
    """Keep mutable local-development choices in a platform-native state path."""

    configured_path = getenv("AGENT_PROVIDER_SETTINGS_PATH", "").strip()
    if configured_path:
        return Path(configured_path)
    if os.name == "nt":
        local_data = Path(getenv("LOCALAPPDATA", r"C:\Users\Default\AppData\Local"))
        return local_data / "Codex" / "finance-agent" / "provider-settings.json"
    state_home = getenv("XDG_STATE_HOME", "").strip()
    local_state = Path(state_home) if state_home else Path.home() / ".local" / "state"
    return local_state / "codex" / "finance-agent" / "provider-settings.json"


class ProviderActivationStore:
    """Persist explicit provider enable/disable choices for the current user.

    Existing providers default to their catalog value so upgrading does not
    silently disable a working setup. Every runtime check rereads this small
    file, allowing a settings-page toggle to affect cached Agent/tool objects.
    """

    def __init__(
        self,
        path: Path | None = None,
        *,
        backend: str | None = None,
        disabled_providers: str | None = None,
    ) -> None:
        self._path = path or default_provider_settings_path()
        self._lock = RLock()
        configured_backend = backend or (
            "local" if path is not None else getenv("AGENT_PROVIDER_ACTIVATION_BACKEND", "local")
        )
        self._backend = configured_backend.strip().lower()
        if self._backend not in {"local", "environment"}:
            raise ProviderActivationError(
                "AGENT_PROVIDER_ACTIVATION_BACKEND must be 'local' or 'environment'"
            )
        configured_disabled = (
            disabled_providers
            if disabled_providers is not None
            else getenv("AGENT_DISABLED_PROVIDERS", "")
        )
        self._disabled_providers = self._parse_disabled_providers(configured_disabled)

    @property
    def writable(self) -> bool:
        """Whether this runtime may persist enablement choices."""

        return self._backend == "local"

    def is_enabled(self, source: str) -> bool:
        definition = get_data_source(source)
        if definition is None:
            raise ValueError("Unknown provider")
        if self._backend == "environment":
            return definition.enabled_by_default and definition.name not in self._disabled_providers
        with self._lock:
            overrides = self._read()
        return overrides.get(definition.name, definition.enabled_by_default)

    def set_enabled(self, source: str, enabled: bool) -> bool:
        definition = get_data_source(source)
        if definition is None:
            raise ValueError("Unknown provider")
        if not isinstance(enabled, bool):
            raise ValueError("Provider enabled state must be boolean")
        if self._backend == "environment":
            raise ProviderActivationError(
                "Provider enablement is managed by deployment configuration and is read-only"
            )
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

    @staticmethod
    def _parse_disabled_providers(raw_value: str) -> frozenset[str]:
        disabled: set[str] = set()
        for raw_name in raw_value.split(","):
            name = raw_name.strip().lower()
            if not name:
                continue
            definition = get_data_source(name)
            if definition is None:
                raise ProviderActivationError(
                    "AGENT_DISABLED_PROVIDERS contains an unknown provider"
                )
            disabled.add(definition.name)
        return frozenset(disabled)
