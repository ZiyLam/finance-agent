from __future__ import annotations

import unittest

from ai_agent.agent import Agent
from ai_agent.memory import ConversationMemory
from ai_agent.messages import ModelResponse, ToolCall
from ai_agent.tools import ToolRegistry, create_echo_tool


class ToolThenTextModel:
    def __init__(self) -> None:
        self._call_count = 0

    def complete(self, messages, tools) -> ModelResponse:  # type: ignore[no-untyped-def]
        del messages, tools
        self._call_count += 1
        if self._call_count == 1:
            return ModelResponse(
                tool_calls=(ToolCall(id="tool-1", name="echo", arguments={"text": "done"}),)
            )
        return ModelResponse(text="Tool result received.")


class AgentTests(unittest.TestCase):
    def test_agent_executes_tool_and_returns_final_text(self) -> None:
        agent = Agent(
            model=ToolThenTextModel(),
            memory=ConversationMemory("Be concise."),
            tools=ToolRegistry((create_echo_tool(),)),
        )

        result = agent.run("Use a tool")

        self.assertEqual(result.text, "Tool result received.")
        self.assertEqual(result.tool_calls[0].name, "echo")

    def test_memory_keeps_system_prompt_when_window_rolls_over(self) -> None:
        memory = ConversationMemory("System", window_size=1)
        agent = Agent(model=ToolThenTextModel(), memory=memory)
        with self.assertRaises(ValueError):
            agent.run("   ")
        self.assertEqual(memory.context()[0].content, "System")


if __name__ == "__main__":
    unittest.main()
