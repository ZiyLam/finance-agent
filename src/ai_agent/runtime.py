"""Composition helpers shared by the CLI, HTTP API, and background workers."""

from __future__ import annotations

from os import getenv

from .secrets import SecretStoreError, resolve_token
from .provider_activation import ProviderActivationStore
from .tools import (
    ToolRegistry,
    create_aktools_market_data_tool,
    create_alltick_market_data_tool,
    create_alphavantage_market_data_tool,
    create_baostock_market_data_tool,
    create_biying_market_data_tool,
    create_eodhd_market_data_tool,
    create_eastmoney_security_search_tool,
    create_eastmoney_market_scan_tool,
    create_echo_tool,
    create_ima_knowledge_search_tool,
    create_tickflow_market_data_tool,
    create_yfinance_market_data_tool,
    create_zhitu_market_data_tool,
)


def build_market_data_tool_registry(*, include_echo: bool = True) -> ToolRegistry:
    """Build read-only data tools without constructing an LLM client.

    Credentials remain server-side.  No network request occurs during registry
    creation; individual tools connect only when an approved research task runs.
    """

    registered_tools = [create_echo_tool()] if include_echo else []
    alltick_token = _provider_token("alltick", "ALLTICK_API_TOKEN", "AllTick")
    if alltick_token:
        from .market_data.alltick import AllTickClient

        registered_tools.append(create_alltick_market_data_tool(AllTickClient(alltick_token)))
    alphavantage_key = _provider_token(
        "alphavantage", "ALPHAVANTAGE_API_KEY", "Alpha Vantage"
    )
    if alphavantage_key:
        from .market_data.alphavantage import AlphaVantageClient

        registered_tools.append(create_alphavantage_market_data_tool(AlphaVantageClient(alphavantage_key)))
    eodhd_token = _provider_token("eodhd", "EODHD_API_TOKEN", "EODHD")
    if eodhd_token:
        from .market_data.eodhd import EODHDClient

        registered_tools.append(create_eodhd_market_data_tool(EODHDClient(eodhd_token)))
    biying_licence = _provider_token("biying", "BIYING_API_LICENCE", "必盈 API")
    if biying_licence:
        from .market_data.biying import BiyingClient

        registered_tools.append(create_biying_market_data_tool(BiyingClient(biying_licence)))
    tickflow_api_key = _provider_token("tickflow", "TICKFLOW_API_KEY", "TickFlow")
    if tickflow_api_key:
        from .market_data.tickflow import TickFlowClient

        registered_tools.append(create_tickflow_market_data_tool(TickFlowClient(tickflow_api_key)))
    zhitu_api_key = _provider_token("zhitu", "ZHITU_API_KEY", "智兔数服")
    if zhitu_api_key:
        from .market_data.zhitu import ZhituClient

        registered_tools.append(create_zhitu_market_data_tool(ZhituClient(zhitu_api_key)))
    try:
        ima_client_id = resolve_token("ima_client_id", "IMA_OPENAPI_CLIENTID")
        ima_api_key = resolve_token("ima_api_key", "IMA_OPENAPI_APIKEY")
    except SecretStoreError as error:
        raise RuntimeError("saved Tencent ima credential cannot be read") from error
    # An explicit name is useful when a user cannot inspect IMA's opaque IDs.
    # Environment configuration overrides the saved default, so changing the
    # name can select a newly created knowledge base without exposing its ID.
    ima_knowledge_base_id = getenv("IMA_KNOWLEDGE_BASE_ID", "").strip()
    ima_knowledge_base_name = getenv("IMA_KNOWLEDGE_BASE_NAME", "").strip()
    if not ima_knowledge_base_id and not ima_knowledge_base_name:
        try:
            ima_knowledge_base_id = resolve_token("ima_knowledge_base_id", "IMA_KNOWLEDGE_BASE_ID") or ""
        except SecretStoreError as error:
            raise RuntimeError("saved Tencent ima knowledge-base target cannot be read") from error
    if ima_client_id and ima_api_key and (ima_knowledge_base_id or ima_knowledge_base_name):
        from .knowledge_base.ima import ImaKnowledgeBaseClient

        registered_tools.append(
            create_ima_knowledge_search_tool(
                ImaKnowledgeBaseClient(
                    ima_client_id,
                    ima_api_key,
                    knowledge_base_id=ima_knowledge_base_id or None,
                    knowledge_base_name=ima_knowledge_base_name or None,
                )
            )
        )
    from .market_data.eastmoney import EastmoneySecuritySearchClient
    from .market_data.aktools import AkToolsClient
    from .market_data.baostock import BaoStockClient
    from .market_data.yfinance import YFinanceClient

    registered_tools.append(create_aktools_market_data_tool(AkToolsClient.from_environment()))
    registered_tools.append(create_baostock_market_data_tool(BaoStockClient()))
    registered_tools.append(create_yfinance_market_data_tool(YFinanceClient()))
    eastmoney_client = EastmoneySecuritySearchClient()
    registered_tools.append(create_eastmoney_security_search_tool(eastmoney_client))
    registered_tools.append(create_eastmoney_market_scan_tool(eastmoney_client))
    activation = ProviderActivationStore()
    return ToolRegistry(
        tuple(registered_tools),
        provider_enabled=activation.is_enabled,
    )


def _provider_token(source: str, environment_variable: str, display_name: str) -> str | None:
    """Resolve one optional provider credential behind a consistent error boundary."""

    try:
        return resolve_token(source, environment_variable)
    except SecretStoreError as error:
        raise RuntimeError(f"saved {display_name} credential cannot be read") from error
