from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch
import unittest

from ai_agent.config import AgentSettings
from ai_agent.messages import ChatMessage, MessageRole
from ai_agent.providers.codex_cli import (
    CodexCliExecutionError,
    CodexCliModelClient,
    CodexCliResponseError,
    _CommandResult,
)
from ai_agent.tools import create_echo_tool


class FakeRunner:
    def __init__(self, payload: object, return_code: int = 0) -> None:
        self.payload = payload
        self.return_code = return_code
        self.calls: list[tuple[list[str], str, Path, float]] = []

    def __call__(
        self,
        command: list[str],
        prompt: str,
        output_path: Path,
        timeout_seconds: float,
    ) -> _CommandResult:
        self.calls.append((command, prompt, output_path, timeout_seconds))
        if self.return_code == 0:
            output_path.write_text(json.dumps(self.payload), encoding="utf-8")
        return _CommandResult(self.return_code)


class CodexCliModelClientTests(unittest.TestCase):
    def test_converts_structured_final_text_into_model_response(self) -> None:
        runner = FakeRunner({"text": "已完成研究摘要。", "tool_calls": []})
        client = CodexCliModelClient(
            executable="codex-test",
            timeout_seconds=45,
            command_runner=runner,
        )

        response = client.complete(
            [
                ChatMessage(MessageRole.SYSTEM, "只做研究。"),
                ChatMessage(MessageRole.USER, "总结风险。"),
            ],
            (create_echo_tool(),),
        )

        self.assertEqual(response.text, "已完成研究摘要。")
        self.assertEqual(response.tool_calls, ())
        command, prompt, _, timeout = runner.calls[0]
        self.assertEqual(command[0:6], ["codex-test", "--sandbox", "read-only", "--ask-for-approval", "never", "exec"])
        self.assertIn("--ephemeral", command)
        self.assertIn("read-only", command)
        self.assertIn("never", command)
        self.assertNotIn("--model", command)
        self.assertEqual(timeout, 45)
        self.assertIn('"name": "echo"', prompt)
        self.assertIn("总结风险。", prompt)

    def test_preserves_valid_local_tool_call(self) -> None:
        runner = FakeRunner(
            {
                "text": "先读取工具。",
                "tool_calls": [
                    {"id": "read-1", "name": "echo", "arguments_json": "{\"text\": \"input\"}"}
                ],
            }
        )
        client = CodexCliModelClient(executable="codex-test", model="configured-model", command_runner=runner)

        response = client.complete(
            [ChatMessage(MessageRole.USER, "调用工具")],
            (create_echo_tool(),),
        )

        self.assertEqual(response.tool_calls[0].name, "echo")
        self.assertEqual(response.tool_calls[0].arguments, {"text": "input"})
        self.assertEqual(runner.calls[0][0][0:8], ["codex-test", "--sandbox", "read-only", "--ask-for-approval", "never", "--model", "configured-model", "exec"])

    def test_rejects_unknown_tool_and_failed_cli_process(self) -> None:
        unknown_tool_runner = FakeRunner(
            {"text": "", "tool_calls": [{"id": "1", "name": "unknown", "arguments_json": "{}"}]}
        )
        client = CodexCliModelClient(executable="codex-test", command_runner=unknown_tool_runner)

        with self.assertRaises(CodexCliResponseError):
            client.complete([ChatMessage(MessageRole.USER, "x")], (create_echo_tool(),))

        failed_client = CodexCliModelClient(
            executable="codex-test",
            command_runner=FakeRunner({}, return_code=1),
        )
        with self.assertRaises(CodexCliExecutionError):
            failed_client.complete([ChatMessage(MessageRole.USER, "x")], ())


class AgentSettingsTests(unittest.TestCase):
    def test_defaults_to_local_codex_cli_and_can_keep_echo_explicit(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            settings = AgentSettings.from_environment()
        self.assertEqual(
            (
                settings.provider,
                settings.model,
                settings.codex_timeout_seconds,
                settings.web_codex_timeout_seconds,
                settings.web_conversation_ttl_seconds,
                settings.web_max_conversations,
            ),
            ("codex", "", 120, 35, 1800, 50),
        )

        with patch.dict(
            "os.environ",
            {"AGENT_PROVIDER": "echo", "AGENT_MODEL": "local-echo"},
            clear=True,
        ):
            echo_settings = AgentSettings.from_environment()
        self.assertEqual((echo_settings.provider, echo_settings.model), ("echo", "local-echo"))

    def test_qianfan_uses_its_default_model_and_timeout(self) -> None:
        with patch.dict("os.environ", {"AGENT_PROVIDER": "qianfan"}, clear=True):
            settings = AgentSettings.from_environment()
        self.assertEqual(
            (settings.provider, settings.model, settings.qianfan_timeout_seconds),
            ("qianfan", "ernie-4.5-turbo-32k", 60),
        )


if __name__ == "__main__":
    unittest.main()
