"""Tool contracts, registration, activation policy, and execution diagnostics."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from time import monotonic
from typing import Any, Protocol

from ..data_sources import get_data_source
from ..observability import elapsed_milliseconds, log_event


class ToolSideEffect(str, Enum):
    """Side-effect capability declared by every Agent-callable tool."""

    READ_ONLY = "read_only"
    MUTATING = "mutating"


class Tool(Protocol):
    """A side-effect-aware capability exposed to an agent."""

    name: str
    description: str
    side_effect: ToolSideEffect

    def run(self, arguments: Mapping[str, Any]) -> str:
        """Validate arguments and return a text result for the model."""


@dataclass(frozen=True, slots=True)
class FunctionTool:
    name: str
    description: str
    handler: Callable[[Mapping[str, Any]], str]
    side_effect: ToolSideEffect = ToolSideEffect.READ_ONLY

    def run(self, arguments: Mapping[str, Any]) -> str:
        return self.handler(arguments)


class ToolRegistry:
    """One controlled lookup point for all agent-callable tools."""

    def __init__(
        self,
        tools: tuple[Tool, ...] = (),
        *,
        provider_enabled: Callable[[str], bool] | None = None,
    ) -> None:
        self._tools: dict[str, Tool] = {}
        self._provider_enabled = provider_enabled or (lambda _source: True)
        for tool in tools:
            self.register(tool)

    def register(self, tool: Tool) -> None:
        if not tool.name or not tool.name.replace("_", "").isalnum():
            raise ValueError("Tool names must contain only letters, numbers, and underscores")
        if tool.name in self._tools:
            raise ValueError(f"A tool named '{tool.name}' is already registered")
        try:
            side_effect = ToolSideEffect(tool.side_effect)
        except (AttributeError, TypeError, ValueError):
            raise ValueError("Agent tools must declare a valid side-effect capability") from None
        if side_effect is not ToolSideEffect.READ_ONLY:
            raise ValueError("The Agent tool registry accepts read-only tools only")
        self._tools[tool.name] = tool

    def execute(self, name: str, arguments: Mapping[str, Any]) -> str:
        """Execute one tool while emitting payload-free diagnostic events."""

        started_at = monotonic()
        source_fields = _source_observability_fields(name)
        tool = self._tools.get(name)
        if tool is None:
            log_event(
                "tool_execution_rejected",
                level=logging.WARNING,
                tool_name=name,
                **source_fields,
                reason="unregistered_tool",
                duration_ms=elapsed_milliseconds(started_at),
            )
            return f"ERROR: Tool '{name}' is not registered."
        provider_name = _TOOL_DATA_SOURCES.get(name)
        if provider_name is not None and not self._provider_is_enabled(provider_name):
            log_event(
                "tool_execution_rejected",
                level=logging.WARNING,
                tool_name=name,
                **source_fields,
                reason="provider_disabled",
                duration_ms=elapsed_milliseconds(started_at),
            )
            return f"ERROR: Provider for tool '{name}' is disabled in parameter settings."
        log_event("tool_execution_started", tool_name=name, **source_fields)
        try:
            output = tool.run(arguments)
        except (TypeError, ValueError, KeyError) as error:
            log_event(
                "tool_execution_rejected",
                level=logging.WARNING,
                tool_name=name,
                **source_fields,
                reason="invalid_input",
                error_type=type(error).__name__,
                duration_ms=elapsed_milliseconds(started_at),
            )
            return f"ERROR: Invalid input for tool '{name}': {error}"
        except Exception as error:  # External tools must not terminate the Agent loop or reveal provider internals.
            log_event(
                "tool_execution_failed",
                level=logging.ERROR,
                tool_name=name,
                **source_fields,
                error_type=type(error).__name__,
                duration_ms=elapsed_milliseconds(started_at),
            )
            return f"ERROR: Tool '{name}' failed unexpectedly; retry later or use another available source."
        log_event(
            "tool_execution_completed",
            tool_name=name,
            **source_fields,
            duration_ms=elapsed_milliseconds(started_at),
            output_characters=len(output) if isinstance(output, str) else None,
        )
        return output

    def definitions(self) -> tuple[Tool, ...]:
        return tuple(
            tool
            for tool in self._tools.values()
            if (
                (provider_name := _TOOL_DATA_SOURCES.get(tool.name)) is None
                or self._provider_is_enabled(provider_name)
            )
        )

    def _provider_is_enabled(self, provider_name: str) -> bool:
        try:
            return self._provider_enabled(provider_name)
        except Exception:
            # Fail closed when the local activation policy cannot be read.
            return False


_TOOL_DATA_SOURCES = {
    "aktools_market_data": "aktools",
    "alltick_market_data": "alltick",
    "alphavantage_market_data": "alphavantage",
    "baostock_market_data": "baostock",
    "biying_market_data": "biying",
    "eastmoney_market_scan": "eastmoney",
    "eastmoney_security_search": "eastmoney",
    "eodhd_market_data": "eodhd",
    "tickflow_market_data": "tickflow",
    "yfinance_market_data": "yfinance",
    "zhitu_market_data": "zhitu",
}
_UNKNOWN_TOOL_DATA_SOURCES = {
    source for source in _TOOL_DATA_SOURCES.values() if get_data_source(source) is None
}
if _UNKNOWN_TOOL_DATA_SOURCES:
    raise RuntimeError("Tool mappings reference unknown data sources")


def _source_observability_fields(tool_name: str) -> dict[str, object]:
    """Attach source priority and latency category to every source timing event."""

    source_name = _TOOL_DATA_SOURCES.get(tool_name)
    definition = get_data_source(source_name) if source_name else None
    if definition is None:
        return {}
    return {
        "data_source": definition.name,
        "latency_class": definition.latency_class.value,
        "routing_priority": definition.routing_priority,
    }


def create_echo_tool() -> FunctionTool:
    """A harmless example tool for integration and smoke testing."""

    def echo(arguments: Mapping[str, Any]) -> str:
        text = arguments.get("text")
        if not isinstance(text, str):
            raise ValueError("'text' must be a string")
        return text

    return FunctionTool("echo", "Returns the supplied text unchanged.", echo)
