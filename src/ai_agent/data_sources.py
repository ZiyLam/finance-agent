"""Central, declarative catalog for data-source credential maintenance.

Adding a definition here automatically makes a source available to the CLI's
``source list``, ``source status``, ``source set-token``, and
``source delete-token`` commands.  A data client and tool registration remain
separate implementation steps, so a stored credential is never sent to an
unimplemented provider by accident.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DataSourceDefinition:
    """One externally maintained data source and its credential policy."""

    name: str
    display_name: str
    token_environment_variable: str
    token_required_by_adapter: bool
    status_description: str = ""
    base_url_environment_variable: str | None = None

    def __post_init__(self) -> None:
        if not self.name.replace("-", "").replace("_", "").isalnum():
            raise ValueError("Data-source names may contain only letters, numbers, hyphens, and underscores")
        if not self.display_name.strip():
            raise ValueError("Data-source display_name cannot be blank")
        if not self.token_environment_variable.strip():
            raise ValueError("Data sources need a token environment-variable name")
        if not self.token_required_by_adapter and not self.status_description.strip():
            raise ValueError("Token-free sources need a status_description")


# Future source integration entry point: add exactly one definition here first.
# Its token-maintenance CLI commands become available immediately.  Set
# token_required_by_adapter=True only after its runtime client consumes it.
DATA_SOURCE_CATALOG = (
    DataSourceDefinition("alltick", "AllTick", "ALLTICK_API_TOKEN", True),
    DataSourceDefinition("alphavantage", "Alpha Vantage", "ALPHAVANTAGE_API_KEY", True),
    DataSourceDefinition("biying", "必盈 API", "BIYING_API_LICENCE", True),
    DataSourceDefinition("eodhd", "EOD Historical Data (EODHD)", "EODHD_API_TOKEN", True),
    DataSourceDefinition(
        "aktools",
        "AkTools / AKShare",
        "AKTOOLS_API_TOKEN",
        False,
        "local AkTools service (checked on demand)",
        "AKTOOLS_BASE_URL",
    ),
    DataSourceDefinition(
        "baostock",
        "BaoStock",
        "BAOSTOCK_API_TOKEN",
        False,
        "anonymous sessions use a local 5,000 requests/day guard",
    ),
    DataSourceDefinition(
        "yfinance",
        "yfinance / Yahoo Finance",
        "YFINANCE_API_TOKEN",
        False,
        "local 1,000 requests/day guard for personal research",
    ),
    DataSourceDefinition(
        "futu",
        "Futu OpenAPI / FutuOpenD",
        "FUTU_API_TOKEN",
        False,
        "local FutuOpenD TCP gateway; OpenD login and market-data permissions are checked on demand",
    ),
)

DATA_SOURCES_BY_NAME = {definition.name: definition for definition in DATA_SOURCE_CATALOG}

if len(DATA_SOURCES_BY_NAME) != len(DATA_SOURCE_CATALOG):
    raise RuntimeError("Data-source names must be unique")
if len({definition.token_environment_variable for definition in DATA_SOURCE_CATALOG}) != len(
    DATA_SOURCE_CATALOG
):
    raise RuntimeError("Data-source token environment-variable names must be unique")


def data_source_names() -> tuple[str, ...]:
    """Return supported source names in the catalog's presentation order."""

    return tuple(definition.name for definition in DATA_SOURCE_CATALOG)


def get_data_source(name: str) -> DataSourceDefinition | None:
    """Resolve a CLI source name without raising for unknown values."""

    return DATA_SOURCES_BY_NAME.get(name.strip().lower())
