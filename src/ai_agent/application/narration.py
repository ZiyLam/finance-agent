"""Evidence-bound optional narrative generation for completed reports."""

from __future__ import annotations

import json
from typing import Protocol

from langchain_core.messages import HumanMessage, SystemMessage

from ..langchain.models import ProviderChatModel
from ..providers.base import ModelClient


class ReportNarrator(Protocol):
    """Generate prose only from the supplied deterministic report summary."""

    def narrate(self, report: dict[str, object]) -> str: ...


class EvidenceBoundNarrator:
    """Use an LLM for wording without granting it tools or raw provider payloads."""

    def __init__(self, model: ModelClient, *, provider_name: str) -> None:
        self._model = model
        self._provider_name = provider_name

    @property
    def provider_name(self) -> str:
        return self._provider_name

    def narrate(self, report: dict[str, object]) -> str:
        evidence = _narration_evidence(report)
        response = ProviderChatModel(client=self._model).invoke(
            [
                SystemMessage(
                    content=(
                        "你是金融研究报告的叙述层。只能基于用户消息中提供的结构化证据写中文摘要。"
                        "不得编造财务、新闻、行情、来源或投资建议；不得执行工具调用；必须保留不确定性、"
                        "数据限制与‘仅供研究与教育，不构成个性化投资建议’的边界。"
                    )
                ),
                HumanMessage(
                    content=(
                        "请将以下证据压缩为简洁的研究性说明，区分事实、限制和下一步核验动作：\n"
                        + json.dumps(evidence, ensure_ascii=False)
                    )
                ),
            ]
        )
        if response.tool_calls or not isinstance(response.content, str) or not response.content.strip():
            raise RuntimeError("narrative provider did not return usable text")
        return response.content.strip()


def _narration_evidence(report: dict[str, object]) -> dict[str, object]:
    """Exclude raw tool results so external text cannot steer the model prompt."""

    fields = (
        "scope",
        "report_status",
        "confidence",
        "summary",
        "market_observations",
        "market_snapshots",
        "cross_source_checks",
        "scenarios",
        "risk_flags",
        "limitations",
        "next_research_actions",
        "disclaimer",
    )
    return {field: report[field] for field in fields if field in report}
