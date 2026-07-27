"""ASGI entry point.  Start with: ``uvicorn ai_agent.api.main:app``."""

from __future__ import annotations

from functools import lru_cache
from os import getenv

from ..application.narration import EvidenceBoundNarrator
from ..providers.codex_cli import CodexCliModelClient
from ..providers.qianfan import DEFAULT_QIANFAN_MODEL, QianfanModelClient
from ..runtime import build_market_data_tool_registry
from ..secrets import SecretStoreError, resolve_token
from .app import create_app


@lru_cache(maxsize=1)
def worker_tool_registry():
    """Keep source guards alive for the lifetime of this development worker."""

    return build_market_data_tool_registry(include_echo=False)


@lru_cache(maxsize=1)
def optional_narrator() -> EvidenceBoundNarrator | None:
    """Build the configured optional evidence-bound narrative provider.

    Personal mode defaults to the model selected by the already signed-in Codex
    CLI.  Qianfan remains an opt-in alternative.  Any missing credential leaves
    deterministic reports available with ``narration_status=not_configured``.
    """

    provider = getenv("AGENT_API_NARRATOR_PROVIDER", "codex").strip().lower()
    if provider == "none":
        return None
    if provider == "codex":
        return EvidenceBoundNarrator(
            CodexCliModelClient(
                model=getenv("AGENT_MODEL", ""),
                timeout_seconds=float(getenv("AGENT_CODEX_TIMEOUT_SECONDS", "120")),
            ),
            provider_name="codex",
        )
    if provider != "qianfan":
        return None
    try:
        api_key = resolve_token("qianfan", "QIANFAN_API_KEY")
    except SecretStoreError:
        return None
    if not api_key:
        return None
    return EvidenceBoundNarrator(
        QianfanModelClient(
            api_key,
            model=getenv("AGENT_QIANFAN_MODEL", DEFAULT_QIANFAN_MODEL),
            timeout_seconds=float(getenv("AGENT_QIANFAN_TIMEOUT_SECONDS", "60")),
        ),
        provider_name="qianfan",
    )


app = create_app(tool_registry_factory=worker_tool_registry, narrator=optional_narrator())
