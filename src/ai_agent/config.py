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
    web_codex_timeout_seconds: float = 35.0
    qianfan_timeout_seconds: float = 60.0
    web_conversation_ttl_seconds: float = 1_800.0
    web_max_conversations: int = 50

    @classmethod
    def from_environment(cls) -> "AgentSettings":
        memory_window = int(getenv("AGENT_MEMORY_WINDOW", "20"))
        if memory_window < 1:
            raise ValueError("AGENT_MEMORY_WINDOW must be at least 1")
        codex_timeout_seconds = float(getenv("AGENT_CODEX_TIMEOUT_SECONDS", "120"))
        if codex_timeout_seconds <= 0:
            raise ValueError("AGENT_CODEX_TIMEOUT_SECONDS must be positive")
        web_codex_timeout_seconds = float(getenv("AGENT_WEB_CODEX_TIMEOUT_SECONDS", "35"))
        if web_codex_timeout_seconds <= 0:
            raise ValueError("AGENT_WEB_CODEX_TIMEOUT_SECONDS must be positive")
        qianfan_timeout_seconds = float(getenv("AGENT_QIANFAN_TIMEOUT_SECONDS", "60"))
        if qianfan_timeout_seconds <= 0:
            raise ValueError("AGENT_QIANFAN_TIMEOUT_SECONDS must be positive")
        web_conversation_ttl_seconds = float(getenv("AGENT_WEB_CONVERSATION_TTL_SECONDS", "1800"))
        if web_conversation_ttl_seconds <= 0:
            raise ValueError("AGENT_WEB_CONVERSATION_TTL_SECONDS must be positive")
        web_max_conversations = int(getenv("AGENT_WEB_MAX_CONVERSATIONS", "50"))
        if web_max_conversations < 1:
            raise ValueError("AGENT_WEB_MAX_CONVERSATIONS must be at least 1")
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
            web_codex_timeout_seconds=web_codex_timeout_seconds,
            qianfan_timeout_seconds=qianfan_timeout_seconds,
            web_conversation_ttl_seconds=web_conversation_ttl_seconds,
            web_max_conversations=web_max_conversations,
        )
