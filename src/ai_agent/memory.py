"""Backward-compatible export for LangChain-backed conversation memory."""

from .langchain.memory import ConversationMemory

__all__ = ["ConversationMemory"]
