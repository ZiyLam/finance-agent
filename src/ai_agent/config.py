"""Configuration that is safe to load from the process environment."""

from __future__ import annotations

from dataclasses import dataclass
from os import getenv


@dataclass(frozen=True, slots=True)
class AgentSettings:
    """Runtime settings shared by the application composition layer."""

    provider: str = "echo"
    model: str = "local-echo"
    system_prompt: str = "You are a helpful AI agent."
    memory_window: int = 20

    @classmethod
    def from_environment(cls) -> "AgentSettings":
        memory_window = int(getenv("AGENT_MEMORY_WINDOW", "20"))
        if memory_window < 1:
            raise ValueError("AGENT_MEMORY_WINDOW must be at least 1")

        return cls(
            provider=getenv("AGENT_PROVIDER", "echo"),
            model=getenv("AGENT_MODEL", "local-echo"),
            system_prompt=getenv("AGENT_SYSTEM_PROMPT", "You are a helpful AI agent."),
            memory_window=memory_window,
        )
