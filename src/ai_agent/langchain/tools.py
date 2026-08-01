"""Adapters that expose the reviewed local tool registry to LangChain."""

from __future__ import annotations

from typing import Any

from pydantic import Field
from langchain_core.tools import BaseTool

from ..tools import ToolRegistry


_MARKET_DATA_PROPERTIES: dict[str, dict[str, object]] = {
    "action": {"type": "string", "description": "Operation supported by the selected data source."},
    "asset_class": {"type": "string", "description": "Asset class required by the source."},
    "codes": {"type": "array", "items": {"type": "string"}, "description": "Source product codes."},
    "code": {"type": "string", "description": "Single provider-specific security code."},
    "symbol": {"type": "string", "description": "Ticker or security symbol."},
    "query": {"type": "string", "description": "Security search text."},
    "keywords": {"type": "string", "description": "Symbol-search keywords."},
    "start_date": {"type": "string", "description": "Inclusive start date in the format required by the source."},
    "end_date": {"type": "string", "description": "End date in the format required by the source."},
    "period": {"type": "string", "description": "Provider-supported candle period."},
    "interval": {"type": "string", "description": "Provider-supported quote interval."},
    "frequency": {"type": "string", "description": "Provider-supported data frequency."},
    "adjust": {"type": "string", "description": "Price-adjustment mode."},
    "adjustflag": {"type": "string", "description": "BaoStock price-adjustment flag."},
    "limit": {"type": "integer", "description": "Maximum number of records to return."},
    "count": {"type": "integer", "description": "Number of records to request."},
    "kline_type": {"type": "integer", "description": "AllTick K-line type."},
    "timestamp_end": {"type": "integer", "description": "AllTick end timestamp in seconds."},
    "auto_adjust": {"type": "boolean", "description": "Whether yfinance should adjust prices."},
}


def _args_schema_for(name: str) -> dict[str, object]:
    if name == "echo":
        return {
            "type": "object",
            "properties": {"text": {"type": "string", "description": "Text to return unchanged."}},
            "required": ["text"],
            "additionalProperties": False,
        }
    return {
        "type": "object",
        "properties": _MARKET_DATA_PROPERTIES,
        "additionalProperties": False,
    }


class RegistryTool(BaseTool):
    """A LangChain ``BaseTool`` backed by the existing read-only registry.

    The registry remains the single execution and error-sanitisation boundary;
    LangChain receives only JSON schemas and normal tool results.
    """

    registry: ToolRegistry = Field(exclude=True)
    args_schema: dict[str, object] = Field(default_factory=dict)

    def _run(self, **arguments: Any) -> str:
        return self.registry.execute(self.name, arguments)


def as_langchain_tools(registry: ToolRegistry) -> tuple[BaseTool, ...]:
    """Convert all reviewed registry tools into LangChain-compatible tools."""

    return tuple(
        RegistryTool(
            name=registered.name,
            description=registered.description,
            registry=registry,
            args_schema=_args_schema_for(registered.name),
        )
        for registered in registry.definitions()
    )
