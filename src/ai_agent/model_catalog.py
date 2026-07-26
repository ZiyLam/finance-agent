"""Declarative model-provider capabilities for deterministic scenario matching."""

from __future__ import annotations

from dataclasses import dataclass

from .analysis_tags import ModelTag


@dataclass(frozen=True, slots=True)
class ModelDefinition:
    """One model provider exposed by the Agent composition layer."""

    provider: str
    display_name: str
    tags: frozenset[ModelTag]
    configuration_note: str

    def __post_init__(self) -> None:
        if not self.provider.replace("_", "").isalnum():
            raise ValueError("Model-provider names may contain only letters, numbers, and underscores")
        if not self.display_name.strip():
            raise ValueError("Model-provider display_name cannot be blank")
        if not self.tags:
            raise ValueError("Model providers require at least one capability tag")


MODEL_CATALOG = (
    ModelDefinition(
        "codex",
        "本机 Codex CLI",
        frozenset(
            {
                ModelTag.FINANCIAL_RESEARCH,
                ModelTag.CHINESE,
                ModelTag.STRUCTURED_RESPONSE,
                ModelTag.AGENT_TOOL_PROTOCOL,
                ModelTag.LOCAL_SELF_TEST,
            }
        ),
        "Uses the locally signed-in Codex CLI; suitable for the current self-test stage.",
    ),
    ModelDefinition(
        "qianfan",
        "百度智能云千帆",
        frozenset(
            {
                ModelTag.FINANCIAL_RESEARCH,
                ModelTag.CHINESE,
                ModelTag.STRUCTURED_RESPONSE,
                ModelTag.AGENT_TOOL_PROTOCOL,
                ModelTag.REMOTE_API,
            }
        ),
        "Requires a saved qianfan credential and an account-authorized model.",
    ),
    ModelDefinition(
        "echo",
        "回显测试模型",
        frozenset({ModelTag.OFFLINE_SMOKE_TEST}),
        "Only for offline framework smoke tests; it is not a research model.",
    ),
)

MODELS_BY_PROVIDER = {definition.provider: definition for definition in MODEL_CATALOG}

if len(MODELS_BY_PROVIDER) != len(MODEL_CATALOG):
    raise RuntimeError("Model-provider names must be unique")


def get_model_definition(provider: str) -> ModelDefinition | None:
    """Resolve a model-provider tag definition without raising for unknown names."""

    return MODELS_BY_PROVIDER.get(provider.strip().lower())
