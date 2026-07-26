"""The bounded orchestration loop that connects model, memory, and tools."""

from __future__ import annotations

from dataclasses import dataclass

from .memory import ConversationMemory
from .messages import ChatMessage, MessageRole, ToolCall
from .providers.base import ModelClient
from .tools import ToolRegistry


@dataclass(frozen=True, slots=True)
class AgentResult:
    text: str
    tool_calls: tuple[ToolCall, ...]


class Agent:
    """Runs a model response loop with a strict maximum number of tool rounds."""

    def __init__(
        self,
        model: ModelClient,
        memory: ConversationMemory,
        tools: ToolRegistry | None = None,
        max_tool_rounds: int = 5,
    ) -> None:
        if max_tool_rounds < 1:
            raise ValueError("max_tool_rounds must be at least 1")
        self._model = model
        self._memory = memory
        self._tools = tools or ToolRegistry()
        self._max_tool_rounds = max_tool_rounds

    def run(self, user_input: str) -> AgentResult:
        if not user_input.strip():
            raise ValueError("user_input cannot be blank")

        self._memory.add(ChatMessage(MessageRole.USER, user_input))
        executed_calls: list[ToolCall] = []

        for _ in range(self._max_tool_rounds):
            response = self._model.complete(self._memory.context(), self._tools.definitions())
            if not response.tool_calls:
                text = response.text or "I could not produce a response."
                self._memory.add(ChatMessage(MessageRole.ASSISTANT, text))
                return AgentResult(text=text, tool_calls=tuple(executed_calls))

            self._memory.add(
                ChatMessage(MessageRole.ASSISTANT, response.text or "", name="tool_request")
            )
            for call in response.tool_calls:
                result = self._tools.execute(call.name, call.arguments)
                self._memory.add(
                    ChatMessage(
                        MessageRole.TOOL,
                        result,
                        name=call.name,
                        tool_call_id=call.id,
                    )
                )
                executed_calls.append(call)

        text = "Tool-call limit reached before the task could be completed."
        self._memory.add(ChatMessage(MessageRole.ASSISTANT, text))
        return AgentResult(text=text, tool_calls=tuple(executed_calls))
