"""LangChain chat-model adapter for the project's existing provider clients."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
import logging
from time import monotonic
from typing import Any

from pydantic import ConfigDict
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool

from ..messages import ChatMessage, MessageRole
from ..observability import elapsed_milliseconds, log_event


@dataclass(frozen=True, slots=True)
class _ProviderToolDescriptor:
    """The name and description consumed by the project's provider boundary."""

    name: str
    description: str

    def run(self, arguments: Mapping[str, Any]) -> str:
        raise RuntimeError("Provider tool descriptors are never executed directly")


class ProviderChatModel(BaseChatModel):
    """Make a legacy provider client usable by LangChain and LangGraph.

    Existing providers intentionally keep their credential handling and HTTP or
    CLI transport.  This adapter is the anti-corruption layer that maps their
    normalized response envelope to LangChain messages and native tool calls.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    # ``ModelClient`` is a runtime Protocol, which Pydantic cannot use for an
    # ``isinstance`` validator.  The adapter validates behavior at invocation.
    client: Any
    bound_tools: tuple[BaseTool, ...] = ()

    @property
    def _llm_type(self) -> str:
        return "finance-agent-provider-adapter"

    @property
    def _identifying_params(self) -> dict[str, object]:
        return {"provider": type(self.client).__name__}

    def bind_tools(
        self,
        tools: Sequence[dict[str, object] | type | Any | BaseTool],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> Runnable[Any, AIMessage]:
        """Bind LangChain tools for the next graph model node."""

        del tool_choice, kwargs
        bound = tuple(tool for tool in tools if isinstance(tool, BaseTool))
        if len(bound) != len(tools):
            raise TypeError("ProviderChatModel requires LangChain BaseTool instances")
        return self.model_copy(update={"bound_tools": bound})

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Call the configured provider and return a LangChain ``AIMessage``."""

        del stop, run_manager, kwargs
        started_at = monotonic()
        log_event(
            "model_completion_started",
            provider=type(self.client).__name__,
            message_count=len(messages),
            available_tool_count=len(self.bound_tools),
        )
        try:
            response = self.client.complete(
                tuple(_to_provider_message(message) for message in messages),
                tuple(_ProviderToolDescriptor(tool.name, tool.description) for tool in self.bound_tools),
            )
        except Exception as error:
            log_event(
                "model_completion_failed",
                level=logging.ERROR,
                provider=type(self.client).__name__,
                error_type=type(error).__name__,
                duration_ms=elapsed_milliseconds(started_at),
            )
            raise
        tool_calls = [
            {"name": call.name, "args": call.arguments, "id": call.id}
            for call in response.tool_calls
        ]
        log_event(
            "model_completion_completed",
            provider=type(self.client).__name__,
            duration_ms=elapsed_milliseconds(started_at),
            requested_tool_count=len(tool_calls),
            requested_tool_names=tuple(call["name"] for call in tool_calls),
        )
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content=response.text or "", tool_calls=tool_calls))]
        )


def _to_provider_message(message: BaseMessage) -> ChatMessage:
    if isinstance(message, SystemMessage):
        role = MessageRole.SYSTEM
    elif isinstance(message, HumanMessage):
        role = MessageRole.USER
    elif isinstance(message, ToolMessage):
        return ChatMessage(
            MessageRole.TOOL,
            _content_to_text(message.content),
            name=message.name,
            tool_call_id=message.tool_call_id,
        )
    elif isinstance(message, AIMessage):
        return ChatMessage(
            MessageRole.ASSISTANT,
            _content_to_text(message.content),
            name="tool_request" if message.tool_calls else None,
        )
    else:
        raise TypeError(f"Unsupported LangChain message type: {type(message).__name__}")
    return ChatMessage(role, _content_to_text(message.content))


def _content_to_text(content: str | list[str | dict[str, object]]) -> str:
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False)
