"""Testing-only model adapter that delegates reasoning to the local Codex CLI.

The adapter uses the operator's existing Codex CLI login and default model. It
does not copy, inspect, or persist Codex credentials. Each completion is an
ephemeral ``codex exec`` invocation in a read-only sandbox with approval set
to ``never``.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from os import name as operating_system_name
from pathlib import Path
from subprocess import CompletedProcess, TimeoutExpired, run
from tempfile import TemporaryDirectory
from typing import Any

from ..messages import ChatMessage, ModelResponse, ToolCall
from ..tools import Tool


class CodexCliError(RuntimeError):
    """Base error for a local Codex CLI completion."""


class CodexCliUnavailableError(CodexCliError):
    """The Codex CLI executable is unavailable from the current process."""


class CodexCliExecutionError(CodexCliError):
    """Codex CLI could not complete a non-interactive model request."""


class CodexCliResponseError(CodexCliError):
    """Codex CLI completed but did not return the expected structured response."""


@dataclass(frozen=True, slots=True)
class _CommandResult:
    return_code: int


CommandRunner = Callable[[Sequence[str], str, Path, float], _CommandResult]


class CodexCliModelClient:
    """Run the configured local Codex CLI model as a bounded Agent provider.

    This is deliberately a self-test integration, not an OpenAI API adapter.
    It relies on the model selected by the local ``codex`` CLI configuration;
    pass ``model`` only when the operator explicitly wants to override that
    local default for this Agent process.
    """

    def __init__(
        self,
        *,
        model: str = "",
        executable: str | None = None,
        timeout_seconds: float = 120.0,
        command_runner: CommandRunner | None = None,
    ) -> None:
        normalized_model = model.strip() if isinstance(model, str) else ""
        if timeout_seconds <= 0:
            raise ValueError("Codex CLI timeout_seconds must be positive")
        self._model = normalized_model
        self._executable = executable or ("codex.cmd" if operating_system_name == "nt" else "codex")
        self._timeout_seconds = timeout_seconds
        self._command_runner = command_runner or self._run_command

    def complete(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[Tool],
    ) -> ModelResponse:
        """Turn normalized context into a text response or local tool requests."""

        known_tool_names = {tool.name for tool in tools}
        prompt = self._build_prompt(messages, tools)
        with TemporaryDirectory(prefix="finance-agent-codex-") as temporary_directory:
            directory = Path(temporary_directory)
            schema_path = directory / "response-schema.json"
            output_path = directory / "response.json"
            schema_path.write_text(
                json.dumps(self._response_schema(), ensure_ascii=False), encoding="utf-8"
            )
            command = self._command(schema_path, output_path)
            try:
                result = self._command_runner(command, prompt, output_path, self._timeout_seconds)
            except FileNotFoundError as error:
                raise CodexCliUnavailableError(
                    "Codex CLI is not available; install it and sign in with 'codex login'"
                ) from error
            except TimeoutExpired as error:
                raise CodexCliExecutionError(
                    "Codex CLI model request timed out; try a shorter question or increase "
                    "AGENT_CODEX_TIMEOUT_SECONDS"
                ) from error
            if result.return_code != 0:
                raise CodexCliExecutionError(
                    "Codex CLI could not complete the model request; verify local Codex login and model access"
                )
            try:
                raw_response = output_path.read_text(encoding="utf-8")
            except OSError as error:
                raise CodexCliResponseError("Codex CLI did not produce a final structured response") from error
        return self._parse_response(raw_response, known_tool_names)

    def _command(self, schema_path: Path, output_path: Path) -> list[str]:
        command = [
            self._executable,
            "--sandbox",
            "read-only",
            "--ask-for-approval",
            "never",
        ]
        if self._model:
            command.extend(("--model", self._model))
        command.extend(
            (
                "exec",
                "--ephemeral",
                "--skip-git-repo-check",
                "--output-schema",
                str(schema_path),
                "--output-last-message",
                str(output_path),
                "--color",
                "never",
            )
        )
        command.append("-")
        return command

    @staticmethod
    def _run_command(
        command: Sequence[str],
        prompt: str,
        output_path: Path,
        timeout_seconds: float,
    ) -> _CommandResult:
        del output_path
        completed: CompletedProcess[str] = run(
            list(command),
            input=prompt,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
        )
        return _CommandResult(completed.returncode)

    @staticmethod
    def _response_schema() -> dict[str, Any]:
        return {
            "type": "object",
            "additionalProperties": False,
            "required": ["text", "tool_calls"],
            "properties": {
                "text": {"type": "string"},
                "tool_calls": {
                    "type": "array",
                    "maxItems": 5,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["id", "name", "arguments_json"],
                        "properties": {
                            "id": {"type": "string", "minLength": 1, "maxLength": 100},
                            "name": {"type": "string", "minLength": 1, "maxLength": 100},
                            "arguments_json": {"type": "string", "minLength": 2, "maxLength": 10_000},
                        },
                    },
                },
            },
        }

    @staticmethod
    def _build_prompt(messages: Sequence[ChatMessage], tools: Sequence[Tool]) -> str:
        transcript = [
            {
                "role": message.role.value,
                "content": message.content,
                "name": message.name,
                "tool_call_id": message.tool_call_id,
            }
            for message in messages
        ]
        available_tools = [
            {"name": tool.name, "description": tool.description}
            for tool in tools
        ]
        return (
            "You are the reasoning model for a local financial-research Agent. "
            "Follow the supplied system instructions and answer the latest user request. "
            "Do not use shell commands, web browsing, or any Codex tools. You may request only "
            "one of the listed local Agent tools when needed. If you request a tool, provide a "
            "valid JSON-object argument map encoded as the 'arguments_json' string and wait for its "
            "result before drawing factual conclusions. "
            "Never claim that a quote is real-time unless the returned data explicitly supports it. "
            "Use the required structured response: put the final user-facing answer in 'text' and "
            "put any requested local Agent calls in 'tool_calls'.\n\n"
            "Available local Agent tools:\n"
            f"{json.dumps(available_tools, ensure_ascii=False)}\n\n"
            "Conversation transcript:\n"
            f"{json.dumps(transcript, ensure_ascii=False)}"
        )

    @staticmethod
    def _parse_response(raw_response: str, known_tool_names: set[str]) -> ModelResponse:
        try:
            payload = json.loads(raw_response)
        except json.JSONDecodeError as error:
            raise CodexCliResponseError("Codex CLI returned invalid structured JSON") from error
        if not isinstance(payload, dict) or set(payload) != {"text", "tool_calls"}:
            raise CodexCliResponseError("Codex CLI response does not match the required response schema")
        text = payload.get("text")
        calls = payload.get("tool_calls")
        if not isinstance(text, str) or not isinstance(calls, list) or len(calls) > 5:
            raise CodexCliResponseError("Codex CLI response has invalid text or tool_calls")
        parsed_calls: list[ToolCall] = []
        ids: set[str] = set()
        for call in calls:
            if not isinstance(call, dict):
                raise CodexCliResponseError("Codex CLI returned an invalid tool call")
            call_id = call.get("id")
            name = call.get("name")
            arguments_json = call.get("arguments_json")
            if (
                not isinstance(call_id, str)
                or not call_id.strip()
                or not isinstance(name, str)
                or name not in known_tool_names
                or not isinstance(arguments_json, str)
                or call_id in ids
            ):
                raise CodexCliResponseError(
                    "Codex CLI requested an unavailable tool or returned malformed tool arguments"
                )
            try:
                arguments = json.loads(arguments_json)
            except json.JSONDecodeError as error:
                raise CodexCliResponseError(
                    "Codex CLI returned invalid JSON for local tool arguments"
                ) from error
            if not isinstance(arguments, dict):
                raise CodexCliResponseError("Codex CLI tool arguments must decode to a JSON object")
            ids.add(call_id)
            parsed_calls.append(ToolCall(id=call_id, name=name, arguments=arguments))
        return ModelResponse(text=text, tool_calls=tuple(parsed_calls))
