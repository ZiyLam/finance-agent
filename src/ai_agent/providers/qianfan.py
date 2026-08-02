"""Baidu Qianfan OpenAI-compatible chat-completions adapter.

The adapter deliberately uses the standard library only.  API credentials are
accepted only at construction time and are never included in errors, prompts,
or logs.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..messages import ChatMessage, ModelResponse
from ..tools import Tool
from .structured_response import build_agent_prompt, parse_agent_response

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
        enabled: Callable[[], bool] | None = None,
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
        self._enabled = enabled or (lambda: True)

    def complete(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[Tool],
    ) -> ModelResponse:
        """Request a structured response without exposing the API credential."""

        try:
            enabled = self._enabled()
        except Exception:
            enabled = False
        if not enabled:
            raise QianfanApiError("Qianfan is disabled in parameter settings.")

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
            error.close()
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
        return build_agent_prompt(messages, tools)

    @staticmethod
    def _parse_response(raw_response: str, known_tool_names: set[str]) -> ModelResponse:
        return parse_agent_response(
            raw_response,
            known_tool_names,
            error_factory=QianfanApiError,
            provider_name="Qianfan",
        )
