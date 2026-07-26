"""A no-network provider used to verify the agent wiring locally."""

from __future__ import annotations

from collections.abc import Sequence

from ..messages import ChatMessage, ModelResponse
from ..tools import Tool


class EchoModelClient:
    """Returns the latest user message; replace this with a real provider adapter."""

    def complete(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[Tool],
    ) -> ModelResponse:
        del tools
        latest_user_message = next(
            (message.content for message in reversed(messages) if message.role == "user"),
            "",
        )
        return ModelResponse(text=f"[echo] {latest_user_message}")
