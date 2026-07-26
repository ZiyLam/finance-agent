"""Provider adapter protocol."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from ..messages import ChatMessage, ModelResponse
from ..tools import Tool


class ModelClient(Protocol):
    """Convert normalized context to a normalized model response."""

    def complete(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[Tool],
    ) -> ModelResponse:
        """Return text and optional tool-call requests without network policy decisions."""
