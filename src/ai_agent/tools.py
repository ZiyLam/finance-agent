"""Tools available to the agent and their central execution boundary."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
from typing import Any, Protocol


class Tool(Protocol):
    """A side-effect-aware capability exposed to an agent."""

    name: str
    description: str

    def run(self, arguments: Mapping[str, Any]) -> str:
        """Validate arguments and return a text result for the model."""


@dataclass(frozen=True, slots=True)
class FunctionTool:
    name: str
    description: str
    handler: Callable[[Mapping[str, Any]], str]

    def run(self, arguments: Mapping[str, Any]) -> str:
        return self.handler(arguments)


class ToolRegistry:
    """One controlled lookup point for all agent-callable tools."""

    def __init__(self, tools: tuple[Tool, ...] = ()) -> None:
        self._tools: dict[str, Tool] = {}
        for tool in tools:
            self.register(tool)

    def register(self, tool: Tool) -> None:
        if not tool.name or not tool.name.replace("_", "").isalnum():
            raise ValueError("Tool names must contain only letters, numbers, and underscores")
        if tool.name in self._tools:
            raise ValueError(f"A tool named '{tool.name}' is already registered")
        self._tools[tool.name] = tool

    def execute(self, name: str, arguments: Mapping[str, Any]) -> str:
        tool = self._tools.get(name)
        if tool is None:
            return f"ERROR: Tool '{name}' is not registered."
        try:
            return tool.run(arguments)
        except (TypeError, ValueError, KeyError) as error:
            return f"ERROR: Invalid input for tool '{name}': {error}"

    def definitions(self) -> tuple[Tool, ...]:
        return tuple(self._tools.values())


def create_echo_tool() -> FunctionTool:
    """A harmless example tool for integration and smoke testing."""

    def echo(arguments: Mapping[str, Any]) -> str:
        text = arguments.get("text")
        if not isinstance(text, str):
            raise ValueError("'text' must be a string")
        return text

    return FunctionTool("echo", "Returns the supplied text unchanged.", echo)


def create_alltick_market_data_tool(client: "AllTickClient") -> FunctionTool:
    """Expose bounded AllTick quote and candle reads to a model provider."""

    from .market_data.alltick import AllTickAssetClass, AllTickKlineType

    def market_data(arguments: Mapping[str, Any]) -> str:
        action = arguments.get("action", "latest_quotes")
        asset_class = AllTickAssetClass(str(arguments.get("asset_class", "stock")))

        if action == "latest_quotes":
            codes = arguments.get("codes")
            if not isinstance(codes, list) or not all(isinstance(code, str) for code in codes):
                raise ValueError("'codes' must be a list of product-code strings")
            quotes = client.latest_quotes(codes, asset_class=asset_class)
            return json.dumps(
                {
                    "source": "AllTick",
                    "quotes": [
                        {
                            "code": quote.code,
                            "timestamp_ms": quote.timestamp_ms,
                            "price": str(quote.price),
                            "volume": str(quote.volume),
                            "turnover": str(quote.turnover),
                            "trade_direction": quote.trade_direction,
                        }
                        for quote in quotes
                    ],
                },
                ensure_ascii=False,
            )

        if action == "historical_candles":
            code = arguments.get("code")
            if not isinstance(code, str):
                raise ValueError("'code' must be a product-code string")
            candles = client.historical_candles(
                code,
                asset_class=asset_class,
                kline_type=AllTickKlineType(int(arguments.get("kline_type", 8))),
                count=int(arguments.get("count", 30)),
                timestamp_end=int(arguments.get("timestamp_end", 0)),
            )
            return json.dumps(
                {
                    "source": "AllTick",
                    "code": code,
                    "candles": [
                        {
                            "timestamp_seconds": candle.timestamp_seconds,
                            "open": str(candle.open_price),
                            "close": str(candle.close_price),
                            "high": str(candle.high_price),
                            "low": str(candle.low_price),
                            "volume": str(candle.volume),
                            "turnover": str(candle.turnover),
                        }
                        for candle in candles
                    ],
                },
                ensure_ascii=False,
            )

        raise ValueError("'action' must be 'latest_quotes' or 'historical_candles'")

    return FunctionTool(
        name="alltick_market_data",
        description=(
            "Reads AllTick latest quotes or historical candles. Inputs: action "
            "('latest_quotes' or 'historical_candles'), asset_class ('stock' or 'other'), "
            "and documented product codes. This tool never trades."
        ),
        handler=market_data,
    )
