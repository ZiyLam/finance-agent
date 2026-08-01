"""Bounded conversation history backed by LangChain's message history type."""

from __future__ import annotations

from langchain_core.chat_history import InMemoryChatMessageHistory
from langchain_core.messages import BaseMessage


class ConversationMemory:
    """Keep a system prompt plus a bounded LangChain message history.

    The system prompt is supplied to ``create_agent`` separately, as LangChain
    expects.  The persisted history therefore contains only user, assistant,
    and tool messages.
    """

    def __init__(self, system_prompt: str, window_size: int = 20) -> None:
        if not isinstance(system_prompt, str) or not system_prompt.strip():
            raise ValueError("system_prompt cannot be blank")
        if window_size < 1:
            raise ValueError("window_size must be at least 1")
        self._system_prompt = system_prompt
        self._window_size = window_size
        self._history = InMemoryChatMessageHistory()

    @property
    def system_prompt(self) -> str:
        """The application-owned instructions passed to the LangChain agent."""

        return self._system_prompt

    def messages(self) -> tuple[BaseMessage, ...]:
        """Return the currently retained LangChain messages."""

        return tuple(self._history.messages)

    def replace(self, messages: list[BaseMessage]) -> None:
        """Persist the latest graph state while enforcing the context window."""

        self._history.clear()
        self._history.add_messages(messages[-self._window_size :])
