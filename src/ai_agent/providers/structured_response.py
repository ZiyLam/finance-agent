"""Shared structured-response protocol for OpenAI-compatible providers."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence

from ..messages import ChatMessage, ModelResponse, ToolCall
from ..tools import Tool


def build_agent_prompt(messages: Sequence[ChatMessage], tools: Sequence[Tool]) -> str:
    """Encode Agent context for models without universally available tool calling."""

    transcript = [
        {
            "role": message.role.value,
            "content": message.content,
            "name": message.name,
            "tool_call_id": message.tool_call_id,
        }
        for message in messages
    ]
    available_tools = [{"name": tool.name, "description": tool.description} for tool in tools]
    return (
        "You are the reasoning model for a local financial-research Agent. "
        "Follow the system instructions in the transcript and answer the latest user request. "
        "Do not browse the web, run shell commands, or invent data. You may request only one "
        "of the listed local Agent tools when needed. If you request a tool, provide a valid "
        "JSON-object argument map encoded as the arguments_json string and wait for its result "
        "before drawing factual conclusions. Never claim that a quote is real-time unless the "
        "returned data explicitly supports it. Do not execute trades or present guaranteed returns. "
        "Return only one JSON object with exactly two keys: text and tool_calls. "
        "text must be a string containing your actual user-facing answer. tool_calls must be an array. "
        "Each tool call must contain id, name, and arguments_json, where arguments_json is a string "
        "that encodes a JSON-object argument map. Use an empty tool_calls array when no tool is needed.\n\n"
        "Available local Agent tools:\n"
        f"{json.dumps(available_tools, ensure_ascii=False)}\n\n"
        "Conversation transcript:\n"
        f"{json.dumps(transcript, ensure_ascii=False)}"
    )


def parse_agent_response(
    raw_response: str,
    known_tool_names: set[str],
    *,
    error_factory: Callable[[str], Exception],
    provider_name: str,
) -> ModelResponse:
    """Validate the stable Agent response envelope from a provider message."""

    normalized = raw_response.strip()
    if normalized.startswith("```") and normalized.endswith("```"):
        lines = normalized.splitlines()
        if len(lines) >= 2:
            normalized = "\n".join(lines[1:-1]).strip()
    try:
        payload = json.loads(normalized)
    except json.JSONDecodeError as error:
        raise error_factory(
            f"{provider_name} did not return the required structured response; try the request again."
        ) from error
    if not isinstance(payload, dict) or set(payload) != {"text", "tool_calls"}:
        raise error_factory(f"{provider_name} response does not match the required response schema.")
    text = payload.get("text")
    calls = payload.get("tool_calls")
    if not isinstance(text, str) or not isinstance(calls, list) or len(calls) > 5:
        raise error_factory(f"{provider_name} response has invalid text or tool_calls.")

    parsed_calls: list[ToolCall] = []
    ids: set[str] = set()
    for call in calls:
        if not isinstance(call, dict):
            raise error_factory(f"{provider_name} returned an invalid local tool call.")
        call_id = call.get("id")
        name = call.get("name")
        arguments_json = call.get("arguments_json")
        if (
            not isinstance(call_id, str)
            or not call_id.strip()
            or call_id in ids
            or not isinstance(name, str)
            or name not in known_tool_names
            or not isinstance(arguments_json, str)
        ):
            raise error_factory(
                f"{provider_name} requested an unavailable tool or returned malformed tool arguments."
            )
        try:
            arguments = json.loads(arguments_json)
        except json.JSONDecodeError as error:
            raise error_factory(f"{provider_name} returned invalid JSON for local tool arguments.") from error
        if not isinstance(arguments, dict):
            raise error_factory(f"{provider_name} tool arguments must decode to a JSON object.")
        ids.add(call_id)
        parsed_calls.append(ToolCall(id=call_id, name=name, arguments=arguments))
    return ModelResponse(text=text, tool_calls=tuple(parsed_calls))
