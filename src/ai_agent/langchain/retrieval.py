"""LCEL retrieval augmentation for personal financial-research requests.

The corpus is application-owned capability guidance, not untrusted Web search
content.  It gives the model and the Web UI grounded information about the
available research boundaries without ever loading a credential or provider
response into a prompt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from langchain_core.documents import Document
from langchain_core.runnables import RunnableLambda, RunnableParallel, RunnablePassthrough

from ..data_sources import DATA_SOURCE_CATALOG
from ..research_planning import SCENARIO_RULES


@dataclass(frozen=True, slots=True)
class IntentAssessment:
    """Broad intent hint for retrieval, never a validity gate on user input."""

    query: str
    name: str
    label: str
    user_role: str
    strategy: str

    @property
    def retrieval_query(self) -> str:
        return f"{self.name} {self.label} {self.query}"

    def to_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "label": self.label,
            "user_role": self.user_role,
            "strategy": self.strategy,
        }


@dataclass(frozen=True, slots=True)
class RetrievedContext:
    """Safe, compact retrieval result used by Agent and Web response paths."""

    query: str
    intent: IntentAssessment
    documents: tuple[Document, ...]

    def prompt_block(self) -> str:
        """Render only trusted, bounded application guidance for an LLM prompt."""

        if not self.documents:
            return "No additional application reference was retrieved."
        sections = []
        sections.append(
            "Intent hint: "
            f"{self.intent.label}. This is a retrieval hint, not a requirement or a replacement for the user's request."
        )
        sections.append(
            f"Inferred user role: {self.intent.user_role}. Required response strategy: {self.intent.strategy}"
        )
        for document in self.documents:
            title = str(document.metadata["title"])
            sections.append(f"[{title}]\n{document.page_content}")
        return "\n\n".join(sections)

    def to_dict(self) -> dict[str, object]:
        """Return presentation metadata rather than reserialising prompt text."""

        return {
            "framework": "lcel_rag",
            "intent": self.intent.to_dict(),
            "document_count": len(self.documents),
            "references": [
                {
                    "id": str(document.metadata["id"]),
                    "title": str(document.metadata["title"]),
                }
                for document in self.documents
            ],
        }


class FinanceLanguageChain:
    """Retrieve concise Finance Agent guidance through a composable LCEL chain.

    A deterministic lexical scorer is intentional for this personal project:
    it keeps the dependency surface small, works offline, and makes retrieval
    reproducible.  The surrounding chain is standard LCEL, so an embedding
    retriever can later replace ``_retrieve_documents`` without changing Agent
    or API contracts.
    """

    def __init__(self, *, max_documents: int = 4) -> None:
        if max_documents < 1:
            raise ValueError("max_documents must be at least 1")
        self._max_documents = max_documents
        self._documents = _knowledge_documents()
        self._chain = (
            RunnableLambda(_detect_intent)
            | RunnableParallel(
                intent=RunnablePassthrough(),
                documents=RunnableLambda(self._retrieve_documents),
            )
            | RunnableLambda(self._to_context)
        )

    def invoke(self, query: str) -> RetrievedContext:
        """Run LCEL retrieval for one user request."""

        normalized = query.strip()
        if not normalized:
            raise ValueError("query cannot be blank")
        return self._chain.invoke(normalized)

    def _retrieve_documents(self, intent: IntentAssessment) -> tuple[Document, ...]:
        query_terms = _terms(intent.retrieval_query)
        scored = [(_score(document, query_terms), index, document) for index, document in enumerate(self._documents)]
        scored.sort(key=lambda item: (-item[0], item[1]))
        positive = [document for score, _index, document in scored if score > 0]
        selected = positive[: self._max_documents]
        # Keep a stable baseline of boundaries/request format when the query
        # overlaps only one specialised document.
        for document in self._documents:
            if len(selected) >= self._max_documents:
                break
            if document not in selected:
                selected.append(document)
        return tuple(selected)

    @staticmethod
    def _to_context(payload: dict[str, object]) -> RetrievedContext:
        return RetrievedContext(
            query=str(payload["intent"].query),  # type: ignore[union-attr]
            intent=payload["intent"],  # type: ignore[arg-type]
            documents=tuple(payload["documents"]),  # type: ignore[arg-type]
        )


def _knowledge_documents() -> tuple[Document, ...]:
    documents = [
        Document(
            page_content=(
                "Finance Agent performs read-only financial research. It must preserve source, "
                "time-validity, uncertainty, limitations, and the statement that output is not "
                "investment advice. It never places orders or promises returns."
            ),
            metadata={"id": "research-boundary", "title": "研究边界与风险提示"},
        ),
        Document(
            page_content=(
                "Natural-language requests work best when they include a security code and, for "
                "history or research reports, a date range such as 2026-01-01 至 2026-03-31 or 最近三个月. "
                "If information is ambiguous, ask a clarification instead of guessing."
            ),
            metadata={"id": "request-format", "title": "自然语言研究请求格式"},
        ),
    ]
    for scenario, rule in SCENARIO_RULES.items():
        documents.append(
            Document(
                page_content=(
                    f"Scenario {scenario.value} supports markets: "
                    f"{', '.join(sorted(market.value for market in rule.allowed_markets))}. "
                    f"Preferred sources: {', '.join(rule.preferred_sources) or 'configured compatible sources'}. "
                    f"Date range required: {'yes' if rule.requires_date_range else 'no'}."
                ),
                metadata={"id": f"scenario-{scenario.value}", "title": f"研究场景：{scenario.value}"},
            )
        )
    for definition in DATA_SOURCE_CATALOG:
        tags = ", ".join(sorted(tag.value for tag in definition.tags)) or "model or maintenance metadata"
        documents.append(
            Document(
                page_content=(
                    f"{definition.display_name} capability tags: {tags}. "
                    f"Credential is {'used by the current adapter' if definition.token_required_by_adapter else 'not used by the current adapter'}."
                ),
                metadata={"id": f"source-{definition.name}", "title": f"数据源：{definition.display_name}"},
            )
        )
    return tuple(documents)


def _terms(value: str) -> set[str]:
    normalized = value.lower()
    ascii_terms = re.findall(r"[a-z0-9_]{2,}", normalized)
    chinese_runs = re.findall(r"[\u4e00-\u9fff]+", normalized)
    chinese_terms = [run[index : index + size] for run in chinese_runs for size in (1, 2, 3) for index in range(len(run) - size + 1)]
    return set(ascii_terms + chinese_terms)


def _score(document: Document, query_terms: set[str]) -> int:
    document_terms = _terms(document.page_content + " " + str(document.metadata["title"]))
    return len(query_terms & document_terms)


def _detect_intent(query: str) -> IntentAssessment:
    """Classify only for better retrieval; every non-empty request remains valid."""

    normalized = query.lower()
    user_role, strategy = _infer_user_role(normalized)
    categories = (
        (
            "market_scan",
            "全市场板块扫描与条件预判",
            ("板块", "行业", "全市场", "市场主线", "值得关注", "热点"),
        ),
        (
            "security_lookup",
            "标的检索与代码识别",
            ("搜索", "查代码", "代码是什么", "找股票", "公司"),
        ),
        (
            "realtime_quote",
            "实时行情与最新价格",
            ("实时", "最新价", "现价", "报价", "多少"),
        ),
        (
            "valuation",
            "估值与指标观察",
            ("估值", "市盈", "市净", "pe", "pb"),
        ),
        (
            "historical_research",
            "历史走势与研究报告",
            ("走势", "历史", "k线", "k 线", "涨跌", "报告", "研报", "研究"),
        ),
    )
    for name, label, terms in categories:
        if any(term in normalized for term in terms):
            return IntentAssessment(query=query, name=name, label=label, user_role=user_role, strategy=strategy)
    return IntentAssessment(
        query=query,
        name="open_ended_research",
        label="开放式金融研究",
        user_role=user_role,
        strategy=strategy,
    )


def _infer_user_role(text: str) -> tuple[str, str]:
    """Infer presentation depth from the request, never from personal data.

    A missing signal deliberately selects an explanation-first presentation.
    This makes broad prompts such as “近期值得关注的板块” useful immediately,
    instead of treating unspecified investing knowledge as a clarification requirement.
    """

    advanced_terms = (
        "专业", "机构", "量化", "因子", "roe", "roic", "fcf", "自由现金流",
        "盈利预测", "估值模型", "beta", "久期", "期权", "隐含波动率",
    )
    intermediate_terms = (
        "估值", "市盈率", "市净率", "财报", "景气度", "资金流", "技术面", "k线", "k 线",
        "毛利率", "现金流", "同比", "环比",
    )
    if any(term in text for term in advanced_terms):
        return (
            "进阶研究者",
            "使用投研框架：说明数据口径、估值/盈利/拥挤度假设、反证条件与待验证资料；避免把模型推演写成事实。",
        )
    if any(term in text for term in intermediate_terms):
        return (
            "有经验的个人研究者",
            "使用结构化解释：给出市场驱动、关键指标、风险情景与继续核验项，并解释术语。",
        )
    return (
        "个人研究者",
        "使用解释型策略：先说清研究范围和数据时效，以平实语言列出不超过三个有依据的候选、驱动、风险和下一步观察点；不要求确认标的。",
    )
