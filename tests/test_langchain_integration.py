from __future__ import annotations

import unittest

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from ai_agent.langchain.models import ProviderChatModel
from ai_agent.langchain.tools import as_langchain_tools
from ai_agent.messages import ModelResponse, ToolCall
from ai_agent.tools import ToolRegistry, create_echo_tool


class ToolCallingProvider:
    def __init__(self) -> None:
        self.messages = ()
        self.tools = ()

    def complete(self, messages, tools):  # type: ignore[no-untyped-def]
        self.messages = tuple(messages)
        self.tools = tuple(tools)
        return ModelResponse(
            text="calling echo",
            tool_calls=(ToolCall(id="call-1", name="echo", arguments={"text": "ready"}),),
        )


class LangChainIntegrationTests(unittest.TestCase):
    def test_model_adapter_maps_messages_and_native_tool_calls(self) -> None:
        provider = ToolCallingProvider()
        tool = as_langchain_tools(ToolRegistry((create_echo_tool(),)))[0]
        model = ProviderChatModel(client=provider).bind_tools([tool])

        response = model.invoke(
            [
                SystemMessage(content="research only"),
                HumanMessage(content="look up a symbol"),
                AIMessage(content="fetching", tool_calls=[{"id": "previous", "name": "echo", "args": {"text": "x"}}]),
                ToolMessage(content="x", name="echo", tool_call_id="previous"),
            ]
        )

        self.assertEqual(response.tool_calls[0]["name"], "echo")
        self.assertEqual(response.tool_calls[0]["args"], {"text": "ready"})
        self.assertEqual(provider.tools[0].name, "echo")
        self.assertEqual(provider.messages[-1].tool_call_id, "previous")

    def test_registry_tools_keep_the_existing_execution_boundary(self) -> None:
        tool = as_langchain_tools(ToolRegistry((create_echo_tool(),)))[0]

        self.assertEqual(tool.invoke({"text": "hello"}), "hello")


if __name__ == "__main__":
    unittest.main()
