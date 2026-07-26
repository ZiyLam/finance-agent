"""Tools available to the agent and their central execution boundary."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
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
