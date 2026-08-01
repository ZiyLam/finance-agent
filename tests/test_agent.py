from __future__ import annotations

import unittest

from ai_agent.langchain.agent import Agent
from ai_agent.langchain.memory import ConversationMemory
from ai_agent.messages import ModelResponse, ToolCall
from ai_agent.tools import ToolRegistry, create_echo_tool


class ToolThenTextModel:
    def __init__(self) -> None:
        self._call_count = 0
        self.last_messages = ()

    def complete(self, messages, tools) -> ModelResponse:  # type: ignore[no-untyped-def]
        self.last_messages = tuple(messages)
        del tools
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
        self.assertEqual(memory.system_prompt, "System")

    def test_agent_keeps_retrieved_context_separate_from_the_user_request(self) -> None:
        model = ToolThenTextModel()
        agent = Agent(model=model, memory=ConversationMemory("System"))

        agent.run("研究 600000", retrieved_context="[研究边界]\n只读研究。")

        message = model.last_messages[-1]
        self.assertIn("Application-owned retrieved reference", message.content)
        self.assertIn("User request:\n研究 600000", message.content)


if __name__ == "__main__":
    unittest.main()
