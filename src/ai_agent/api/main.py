"""ASGI entry point.  Start with: ``uvicorn ai_agent.api.main:app``."""

from __future__ import annotations

from functools import lru_cache
from os import getenv
from pathlib import Path

from ..application.narration import EvidenceBoundNarrator
from ..application.source_connectivity import SourceConnectivityService
from ..application.source_credentials import SourceCredentialService
from ..application.web_workspace import WebWorkspaceService
from ..config import AgentSettings
from ..langchain.agent import Agent
from ..langchain.memory import ConversationMemory
from ..provider_activation import ProviderActivationStore
from ..providers.codex_cli import CodexCliModelClient
from ..providers.echo import EchoModelClient
from ..providers.qianfan import DEFAULT_QIANFAN_MODEL, QianfanModelClient
from ..runtime import build_market_data_tool_registry
from ..secrets import SecretStoreError, resolve_token
from ..skills import compose_system_prompt, load_skills
from .app import create_app


@lru_cache(maxsize=1)
def worker_tool_registry():
    """Keep source guards alive for the lifetime of this development worker."""

    return build_market_data_tool_registry(include_echo=False)


@lru_cache(maxsize=1)
def web_tool_registry():
    """Expose the configured, read-only tools to the LangChain Web Agent."""

    return build_market_data_tool_registry(include_echo=True)


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
            enabled=lambda: ProviderActivationStore().is_enabled("qianfan"),
        ),
        provider_name="qianfan",
    )


def build_web_agent() -> Agent:
    """Build one conversation-scoped LangChain Agent for the personal Web UI."""

    settings = AgentSettings.from_environment()
    if settings.provider == "echo":
        model = EchoModelClient()
    elif settings.provider == "codex":
        model = CodexCliModelClient(
            model=settings.model,
            timeout_seconds=settings.web_codex_timeout_seconds,
        )
    elif settings.provider == "qianfan":
        try:
            api_key = resolve_token("qianfan", "QIANFAN_API_KEY")
        except SecretStoreError as error:
            raise RuntimeError("The saved Qianfan credential cannot be read.") from error
        if not api_key:
            raise RuntimeError("Qianfan is selected but no API key is configured.")
        model = QianfanModelClient(
            api_key,
            model=settings.model,
            timeout_seconds=settings.qianfan_timeout_seconds,
            enabled=lambda: ProviderActivationStore().is_enabled("qianfan"),
        )
    else:
        raise RuntimeError("The configured Web model provider is not supported.")

    project_root = Path(__file__).resolve().parents[3]
    system_prompt = compose_system_prompt(settings.system_prompt, load_skills(project_root / "skills"))
    return Agent(
        model=model,
        memory=ConversationMemory(system_prompt, settings.memory_window),
        tools=web_tool_registry(),
        max_tool_rounds=2,
    )


def create_web_workspace() -> WebWorkspaceService:
    """Compose the Web entry point with the same LangChain and data-tool runtime."""

    settings = AgentSettings.from_environment()
    return WebWorkspaceService(
        tool_registry_factory=worker_tool_registry,
        agent_factory=build_web_agent,
        model_provider=settings.provider,
        narrator=optional_narrator(),
        session_ttl_seconds=settings.web_conversation_ttl_seconds,
        max_conversations=settings.web_max_conversations,
    )


@lru_cache(maxsize=1)
def source_credentials() -> SourceCredentialService:
    """Use the current Windows user's DPAPI-protected local token store."""

    return SourceCredentialService()


@lru_cache(maxsize=1)
def source_connectivity() -> SourceConnectivityService:
    """Compose bounded, on-demand source smoke tests for the settings page."""

    return SourceConnectivityService(
        timeout_seconds=float(getenv("AGENT_SOURCE_CHECK_TIMEOUT_SECONDS", "4")),
        max_parallel_checks=int(getenv("AGENT_SOURCE_CHECK_MAX_PARALLEL", "4")),
    )


app = create_app(
    tool_registry_factory=worker_tool_registry,
    narrator=optional_narrator(),
    web_workspace=create_web_workspace(),
    source_credentials=source_credentials(),
    source_connectivity=source_connectivity(),
)
