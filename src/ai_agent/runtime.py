"""Composition helpers shared by the CLI, HTTP API, and background workers."""

from __future__ import annotations

from .secrets import SecretStoreError, resolve_token
from .tools import (
    ToolRegistry,
    create_aktools_market_data_tool,
    create_alltick_market_data_tool,
    create_alphavantage_market_data_tool,
    create_baostock_market_data_tool,
    create_biying_market_data_tool,
    create_eodhd_market_data_tool,
    create_echo_tool,
    create_yfinance_market_data_tool,
)


def build_market_data_tool_registry(*, include_echo: bool = True) -> ToolRegistry:
    """Build read-only data tools without constructing an LLM client.

    Credentials remain server-side.  No network request occurs during registry
    creation; individual tools connect only when an approved research task runs.
    """

    registered_tools = [create_echo_tool()] if include_echo else []
    try:
        alltick_token = resolve_token("alltick", "ALLTICK_API_TOKEN")
    except SecretStoreError as error:
        raise RuntimeError("saved AllTick credential cannot be read") from error
    if alltick_token:
        from .market_data.alltick import AllTickClient

        registered_tools.append(create_alltick_market_data_tool(AllTickClient(alltick_token)))
    try:
        alphavantage_key = resolve_token("alphavantage", "ALPHAVANTAGE_API_KEY")
    except SecretStoreError as error:
        raise RuntimeError("saved Alpha Vantage credential cannot be read") from error
    if alphavantage_key:
        from .market_data.alphavantage import AlphaVantageClient

        registered_tools.append(create_alphavantage_market_data_tool(AlphaVantageClient(alphavantage_key)))
    try:
        eodhd_token = resolve_token("eodhd", "EODHD_API_TOKEN")
    except SecretStoreError as error:
        raise RuntimeError("saved EODHD credential cannot be read") from error
    if eodhd_token:
        from .market_data.eodhd import EODHDClient

        registered_tools.append(create_eodhd_market_data_tool(EODHDClient(eodhd_token)))
    try:
        biying_licence = resolve_token("biying", "BIYING_API_LICENCE")
    except SecretStoreError as error:
        raise RuntimeError("saved 必盈 API credential cannot be read") from error
    if biying_licence:
        from .market_data.biying import BiyingClient

        registered_tools.append(create_biying_market_data_tool(BiyingClient(biying_licence)))
    from .market_data.aktools import AkToolsClient
    from .market_data.baostock import BaoStockClient
    from .market_data.yfinance import YFinanceClient

    registered_tools.append(create_aktools_market_data_tool(AkToolsClient.from_environment()))
    registered_tools.append(create_baostock_market_data_tool(BaoStockClient()))
    registered_tools.append(create_yfinance_market_data_tool(YFinanceClient()))
    return ToolRegistry(tuple(registered_tools))
