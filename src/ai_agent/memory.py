"""Conversation memory with a bounded, predictable context window."""

from __future__ import annotations

from collections import deque

from .messages import ChatMessage, MessageRole


class ConversationMemory:
    """Retains one system message plus the newest non-system messages."""

    def __init__(self, system_prompt: str, window_size: int = 20) -> None:
        if window_size < 1:
            raise ValueError("window_size must be at least 1")
        self._system = ChatMessage(MessageRole.SYSTEM, system_prompt)
        self._messages: deque[ChatMessage] = deque(maxlen=window_size)

    def add(self, message: ChatMessage) -> None:
        if message.role is MessageRole.SYSTEM:
            raise ValueError("ConversationMemory manages the system message itself")
        self._messages.append(message)

    def context(self) -> tuple[ChatMessage, ...]:
        return (self._system, *self._messages)
