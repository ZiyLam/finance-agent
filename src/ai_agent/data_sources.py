"""Central, declarative catalog for data-source credential maintenance.

Adding a definition here automatically makes a source available to the CLI's
``source list``, ``source status``, ``source set-token``, and
``source delete-token`` commands.  A data client and tool registration remain
separate implementation steps, so a stored credential is never sent to an
unimplemented provider by accident.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .analysis_tags import DataSourceTag


class DataSourceLatencyClass(StrEnum):
    """Coarse observed-latency category used as a deterministic routing tie-breaker.

    It is intentionally not an SLA.  Actual call duration remains available in
    the payload-free ``tool_execution_*`` logs for operational review.
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    UNKNOWN = "unknown"


class SourceConfigurationGroup(StrEnum):
    """Settings-page ownership for external providers.

    The credential catalog remains shared so its security and maintenance
    behavior stays consistent, while market data and LLM providers are
    presented as separate modules.
    """

    DATA_SOURCE = "data_source"
    LLM = "llm"


_LATENCY_CLASS_RANK = {
    DataSourceLatencyClass.LOW: 1,
    DataSourceLatencyClass.MEDIUM: 2,
    DataSourceLatencyClass.HIGH: 3,
    DataSourceLatencyClass.UNKNOWN: 4,
}


@dataclass(frozen=True, slots=True)
class DataSourceDefinition:
    """One externally maintained data source and its credential policy."""

    name: str
    display_name: str
    token_environment_variable: str
    token_required_by_adapter: bool
    status_description: str = ""
    base_url_environment_variable: str | None = None
    tags: frozenset[DataSourceTag] = frozenset()
    routing_priority: int = 100
    latency_class: DataSourceLatencyClass = DataSourceLatencyClass.UNKNOWN
    configuration_group: SourceConfigurationGroup = SourceConfigurationGroup.DATA_SOURCE
    enabled_by_default: bool = True

    def __post_init__(self) -> None:
        if not self.name.replace("-", "").replace("_", "").isalnum():
            raise ValueError("Data-source names may contain only letters, numbers, hyphens, and underscores")
        if not self.display_name.strip():
            raise ValueError("Data-source display_name cannot be blank")
        if not self.token_environment_variable.strip():
            raise ValueError("Data sources need a token environment-variable name")
        if not self.token_required_by_adapter and not self.status_description.strip():
            raise ValueError("Token-free sources need a status_description")
        if not all(isinstance(tag, DataSourceTag) for tag in self.tags):
            raise ValueError("Data-source tags must be DataSourceTag values")
        if (
            not isinstance(self.routing_priority, int)
            or isinstance(self.routing_priority, bool)
            or self.routing_priority < 1
        ):
            raise ValueError("Data-source routing_priority must be a positive integer")
        if not isinstance(self.latency_class, DataSourceLatencyClass):
            raise ValueError("Data-source latency_class must be a DataSourceLatencyClass")
        if not isinstance(self.configuration_group, SourceConfigurationGroup):
            raise ValueError("Provider configuration_group must be a SourceConfigurationGroup")
        if not isinstance(self.enabled_by_default, bool):
            raise ValueError("Provider enabled_by_default must be boolean")

    @property
    def latency_rank(self) -> int:
        """Return a stable sort rank; lower expected latency runs first."""

        return _LATENCY_CLASS_RANK[self.latency_class]


# Future source integration entry point: add exactly one dictionary entry here.
# Token maintenance then becomes available immediately; runtime client and tool
# registration remain separate so unused credentials are never transmitted.
DATA_SOURCES_BY_NAME: dict[str, DataSourceDefinition] = {
    "alltick": DataSourceDefinition(
        "alltick",
        "AllTick",
        "ALLTICK_API_TOKEN",
        True,
        tags=frozenset(
            {
                DataSourceTag.A_SHARE,
                DataSourceTag.GLOBAL_MARKETS,
                DataSourceTag.MULTI_ASSET,
                DataSourceTag.REALTIME_QUOTE,
                DataSourceTag.HISTORICAL_OHLCV,
            }
        ),
        routing_priority=30,
        latency_class=DataSourceLatencyClass.MEDIUM,
    ),
    "alphavantage": DataSourceDefinition(
        "alphavantage",
        "Alpha Vantage",
        "ALPHAVANTAGE_API_KEY",
        True,
        tags=frozenset(
            {
                DataSourceTag.GLOBAL_MARKETS,
                DataSourceTag.SYMBOL_SEARCH,
                DataSourceTag.END_OF_DAY_QUOTE,
                DataSourceTag.HISTORICAL_OHLCV,
            }
        ),
        routing_priority=60,
        latency_class=DataSourceLatencyClass.HIGH,
    ),
    "biying": DataSourceDefinition(
        "biying",
        "必盈 API",
        "BIYING_API_LICENCE",
        True,
        tags=frozenset(
            {
                DataSourceTag.A_SHARE,
                DataSourceTag.SYMBOL_SEARCH,
                DataSourceTag.REALTIME_QUOTE,
                DataSourceTag.VALUATION_METRICS,
            }
        ),
        routing_priority=20,
        latency_class=DataSourceLatencyClass.LOW,
    ),
    "eodhd": DataSourceDefinition(
        "eodhd",
        "EOD Historical Data (EODHD)",
        "EODHD_API_TOKEN",
        True,
        tags=frozenset(
            {
                DataSourceTag.GLOBAL_MARKETS,
                DataSourceTag.SYMBOL_SEARCH,
                DataSourceTag.HISTORICAL_OHLCV,
                DataSourceTag.DATE_BOUNDED_HISTORICAL,
            }
        ),
        routing_priority=40,
        latency_class=DataSourceLatencyClass.MEDIUM,
    ),
    "eastmoney": DataSourceDefinition(
        "eastmoney",
        "东方财富公开行情检索",
        "EASTMONEY_API_TOKEN",
        False,
        "public A-share security-name and industry-ranking lookup; no personal token is used",
        # The exposed adapter searches securities and samples industry rankings;
        # it does not expose a historical OHLCV endpoint.
        tags=frozenset({DataSourceTag.A_SHARE, DataSourceTag.SYMBOL_SEARCH}),
        routing_priority=10,
        latency_class=DataSourceLatencyClass.LOW,
    ),
    "zhitu": DataSourceDefinition(
        "zhitu",
        "智兔数服",
        "ZHITU_API_KEY",
        True,
        tags=frozenset(
            {
                DataSourceTag.A_SHARE,
                DataSourceTag.REALTIME_QUOTE,
                DataSourceTag.HISTORICAL_OHLCV,
                DataSourceTag.DATE_BOUNDED_HISTORICAL,
            }
        ),
        # 官网文档标明最高 300 次/分钟起。运行时会以该保守下限限流；
        # 实际耗时仍以 tool_execution_* 日志为准。
        routing_priority=15,
        latency_class=DataSourceLatencyClass.MEDIUM,
    ),
    "qianfan": DataSourceDefinition(
        "qianfan",
        "百度智能云千帆 LLM",
        "QIANFAN_API_KEY",
        True,
        routing_priority=100,
        latency_class=DataSourceLatencyClass.UNKNOWN,
        configuration_group=SourceConfigurationGroup.LLM,
    ),
    "aktools": DataSourceDefinition(
        "aktools",
        "AkTools / AKShare",
        "AKTOOLS_API_TOKEN",
        False,
        "local AkTools service (checked on demand)",
        "AKTOOLS_BASE_URL",
        frozenset(
            {
                DataSourceTag.A_SHARE,
                DataSourceTag.HISTORICAL_OHLCV,
                DataSourceTag.DATE_BOUNDED_HISTORICAL,
                DataSourceTag.LOCAL_SERVICE,
            }
        ),
        routing_priority=10,
        latency_class=DataSourceLatencyClass.LOW,
    ),
    "baostock": DataSourceDefinition(
        "baostock",
        "BaoStock",
        "BAOSTOCK_API_TOKEN",
        False,
        "anonymous sessions use a local 5,000 requests/day guard",
        tags=frozenset(
            {
                DataSourceTag.A_SHARE,
                DataSourceTag.HISTORICAL_OHLCV,
                DataSourceTag.DATE_BOUNDED_HISTORICAL,
            }
        ),
        routing_priority=30,
        latency_class=DataSourceLatencyClass.MEDIUM,
    ),
    "yfinance": DataSourceDefinition(
        "yfinance",
        "yfinance / Yahoo Finance",
        "YFINANCE_API_TOKEN",
        False,
        "local 1,000 requests/day guard for personal research",
        tags=frozenset(
            {
                DataSourceTag.GLOBAL_MARKETS,
                DataSourceTag.MULTI_ASSET,
                DataSourceTag.END_OF_DAY_QUOTE,
                DataSourceTag.HISTORICAL_OHLCV,
                DataSourceTag.DATE_BOUNDED_HISTORICAL,
            }
        ),
        routing_priority=70,
        latency_class=DataSourceLatencyClass.HIGH,
    ),
    "tickflow": DataSourceDefinition(
        "tickflow",
        "TickFlow",
        "TICKFLOW_API_KEY",
        True,
        tags=frozenset(
            {
                DataSourceTag.A_SHARE,
                DataSourceTag.GLOBAL_MARKETS,
                DataSourceTag.MULTI_ASSET,
                DataSourceTag.REALTIME_QUOTE,
                DataSourceTag.HISTORICAL_OHLCV,
                DataSourceTag.DATE_BOUNDED_HISTORICAL,
            }
        ),
        routing_priority=15,
        latency_class=DataSourceLatencyClass.LOW,
    ),
}

if any(name != definition.name for name, definition in DATA_SOURCES_BY_NAME.items()):
    raise RuntimeError("Data-source catalog keys must match their definitions")

DATA_SOURCE_CATALOG = tuple(DATA_SOURCES_BY_NAME.values())

if len(DATA_SOURCES_BY_NAME) != len(DATA_SOURCE_CATALOG):
    raise RuntimeError("Data-source names must be unique")
if len({definition.token_environment_variable for definition in DATA_SOURCE_CATALOG}) != len(
    DATA_SOURCE_CATALOG
):
    raise RuntimeError("Data-source token environment-variable names must be unique")


def data_source_names() -> tuple[str, ...]:
    """Return supported source names in their deterministic execution order."""

    return tuple(definition.name for definition in ordered_data_sources())


def ordered_data_sources() -> tuple[DataSourceDefinition, ...]:
    """Order source status views by priority, then expected latency and name."""

    return tuple(
        sorted(
            DATA_SOURCE_CATALOG,
            key=lambda definition: (definition.routing_priority, definition.latency_rank, definition.name),
        )
    )


def configurations_in_group(
    group: SourceConfigurationGroup | str,
) -> tuple[DataSourceDefinition, ...]:
    """Return one settings module in the catalog's deterministic order."""

    normalized_group = (
        group if isinstance(group, SourceConfigurationGroup) else SourceConfigurationGroup(group)
    )
    return tuple(
        definition
        for definition in ordered_data_sources()
        if definition.configuration_group is normalized_group
    )


def get_data_source(name: str) -> DataSourceDefinition | None:
    """Resolve a CLI source name without raising for unknown values."""

    return DATA_SOURCES_BY_NAME.get(name.strip().lower())
