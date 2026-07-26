"""Baidu Qianfan OpenAI-compatible chat-completions adapter.

The adapter deliberately uses the standard library only.  API credentials are
accepted only at construction time and are never included in errors, prompts,
or logs.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
import json
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..messages import ChatMessage, ModelResponse, ToolCall
from ..tools import Tool


QIANFAN_CHAT_COMPLETIONS_URL = "https://qianfan.baidubce.com/v2/chat/completions"
DEFAULT_QIANFAN_MODEL = "ernie-4.5-turbo-32k"


class QianfanError(RuntimeError):
    """Base class for safe, user-facing Qianfan provider errors."""


class QianfanApiError(QianfanError):
    """The Qianfan API rejected a request without exposing its response body."""


class QianfanRateLimitError(QianfanError):
    """Qianfan temporarily limited requests."""


class QianfanTransportError(QianfanError):
    """The Qianfan API could not be reached or returned malformed data."""


class _HttpResponse(Protocol):
    def read(self) -> bytes: ...

    def __enter__(self) -> "_HttpResponse": ...

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None: ...


Transport = Callable[[Request, float], _HttpResponse]


class QianfanModelClient:
    """Translate Agent context into Qianfan requests and normalized responses."""

    def __init__(
        self,
        api_key: str,
        *,
        model: str = DEFAULT_QIANFAN_MODEL,
        timeout_seconds: float = 60.0,
        transport: Transport | None = None,
    ) -> None:
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("Qianfan API key must not be blank")
        if not isinstance(model, str) or not model.strip():
            raise ValueError("Qianfan model must not be blank")
        if timeout_seconds <= 0:
            raise ValueError("Qianfan timeout_seconds must be positive")
        self._api_key = api_key.strip()
        self._model = model.strip()
        self._timeout_seconds = timeout_seconds
        self._transport = transport or self._urlopen

    def complete(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[Tool],
    ) -> ModelResponse:
        """Request a structured response without exposing the API credential."""

        request_payload = {
            "model": self._model,
            "messages": [{"role": "user", "content": self._build_prompt(messages, tools)}],
            "stream": False,
        }
        request = Request(
            QIANFAN_CHAT_COMPLETIONS_URL,
            data=json.dumps(request_payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json; charset=utf-8",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with self._transport(request, self._timeout_seconds) as response:
                response_bytes = response.read()
        except HTTPError as error:
            if error.code == 429:
                raise QianfanRateLimitError(
                    "Qianfan rate limit reached; wait briefly and try again."
                ) from error
            if error.code in {401, 403}:
                raise QianfanApiError(
                    "Qianfan authentication was rejected; update the saved qianfan token or QIANFAN_API_KEY."
                ) from error
            raise QianfanApiError(
                "Qianfan API rejected the request; verify model access and request limits."
            ) from error
        except (TimeoutError, URLError, OSError) as error:
            raise QianfanTransportError(
                "Could not reach Qianfan; check network access and try again."
            ) from error

        try:
            response_payload = json.loads(response_bytes.decode("utf-8"))
            content = response_payload["choices"][0]["message"]["content"]
        except (UnicodeDecodeError, TypeError, KeyError, IndexError, json.JSONDecodeError) as error:
            raise QianfanTransportError(
                "Qianfan returned an unexpected response format; try again later."
            ) from error
        if not isinstance(content, str):
            raise QianfanTransportError("Qianfan returned an empty or invalid message content.")
        return self._parse_response(content, {tool.name for tool in tools})

    @staticmethod
    def _urlopen(request: Request, timeout_seconds: float) -> _HttpResponse:
        return urlopen(request, timeout=timeout_seconds)  # noqa: S310 - fixed HTTPS endpoint

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
        available_tools = [{"name": tool.name, "description": tool.description} for tool in tools]
        return (
            "You are the reasoning model for a local financial-research Agent. "
            "Follow the system instructions in the transcript and answer the latest user request. "
            "Do not browse the web, run shell commands, or invent data. You may request only one "
            "of the listed local Agent tools when needed. If you request a tool, provide a valid "
            "JSON-object argument map encoded as the arguments_json string and wait for its result "
            "before drawing factual conclusions. Never claim that a quote is real-time unless the "
            "returned data explicitly supports it. Do not execute trades or present guaranteed returns. "
            "Return JSON only, with exactly this envelope: "
            '{"text":"user-facing answer","tool_calls":[{"id":"unique id","name":"tool name",'
            '"arguments_json":"{...}"}]}. Use an empty tool_calls array when no tool is needed.\n\n'
            "Available local Agent tools:\n"
            f"{json.dumps(available_tools, ensure_ascii=False)}\n\n"
            "Conversation transcript:\n"
            f"{json.dumps(transcript, ensure_ascii=False)}"
        )

    @staticmethod
    def _parse_response(raw_response: str, known_tool_names: set[str]) -> ModelResponse:
        normalized = raw_response.strip()
        if normalized.startswith("```") and normalized.endswith("```"):
            lines = normalized.splitlines()
            if len(lines) >= 2:
                normalized = "\n".join(lines[1:-1]).strip()
        try:
            payload = json.loads(normalized)
        except json.JSONDecodeError as error:
            raise QianfanApiError(
                "Qianfan did not return the required structured response; try the request again."
            ) from error
        if not isinstance(payload, dict) or set(payload) != {"text", "tool_calls"}:
            raise QianfanApiError("Qianfan response does not match the required response schema.")
        text = payload.get("text")
        calls = payload.get("tool_calls")
        if not isinstance(text, str) or not isinstance(calls, list) or len(calls) > 5:
            raise QianfanApiError("Qianfan response has invalid text or tool_calls.")

        parsed_calls: list[ToolCall] = []
        ids: set[str] = set()
        for call in calls:
            if not isinstance(call, dict):
                raise QianfanApiError("Qianfan returned an invalid local tool call.")
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
                raise QianfanApiError(
                    "Qianfan requested an unavailable tool or returned malformed tool arguments."
                )
            try:
                arguments = json.loads(arguments_json)
            except json.JSONDecodeError as error:
                raise QianfanApiError("Qianfan returned invalid JSON for local tool arguments.") from error
            if not isinstance(arguments, dict):
                raise QianfanApiError("Qianfan tool arguments must decode to a JSON object.")
            ids.add(call_id)
            parsed_calls.append(ToolCall(id=call_id, name=name, arguments=arguments))
        return ModelResponse(text=text, tool_calls=tuple(parsed_calls))
