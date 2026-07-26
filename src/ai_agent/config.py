"""Configuration that is safe to load from the process environment."""

from __future__ import annotations

from dataclasses import dataclass
from os import getenv


@dataclass(frozen=True, slots=True)
class AgentSettings:
    """Runtime settings shared by the application composition layer."""

    provider: str = "codex"
    model: str = ""
    system_prompt: str = "You are a helpful AI agent."
    memory_window: int = 20
    codex_timeout_seconds: float = 120.0
    qianfan_timeout_seconds: float = 60.0

    @classmethod
    def from_environment(cls) -> "AgentSettings":
        memory_window = int(getenv("AGENT_MEMORY_WINDOW", "20"))
        if memory_window < 1:
            raise ValueError("AGENT_MEMORY_WINDOW must be at least 1")
        codex_timeout_seconds = float(getenv("AGENT_CODEX_TIMEOUT_SECONDS", "120"))
        if codex_timeout_seconds <= 0:
            raise ValueError("AGENT_CODEX_TIMEOUT_SECONDS must be positive")
        qianfan_timeout_seconds = float(getenv("AGENT_QIANFAN_TIMEOUT_SECONDS", "60"))
        if qianfan_timeout_seconds <= 0:
            raise ValueError("AGENT_QIANFAN_TIMEOUT_SECONDS must be positive")
        provider = getenv("AGENT_PROVIDER", "codex").strip().lower()
        configured_model = getenv("AGENT_MODEL", "")
        if provider == "qianfan" and not configured_model.strip():
            configured_model = "ernie-4.5-turbo-32k"

        return cls(
            provider=provider,
            model=configured_model,
            system_prompt=getenv("AGENT_SYSTEM_PROMPT", "You are a helpful AI agent."),
            memory_window=memory_window,
            codex_timeout_seconds=codex_timeout_seconds,
            qianfan_timeout_seconds=qianfan_timeout_seconds,
        )
