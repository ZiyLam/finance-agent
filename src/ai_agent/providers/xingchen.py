"""iFlytek Xingchen MaaS HTTP inference adapter.

The public Xingchen documentation specifies an OpenAI-compatible
``/chat/completions`` API.  The actual model ID and API base are assigned per
published service, so both remain operator-configurable.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
import json
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from ..messages import ChatMessage, ModelResponse
from ..tools import Tool
from .structured_response import build_agent_prompt, parse_agent_response


DEFAULT_XINGCHEN_API_BASE = "https://maas-api.cn-huabei-1.xf-yun.com/v2"


class XingchenError(RuntimeError):
    """Base class for safe, user-facing Xingchen provider errors."""


class XingchenApiError(XingchenError):
    """Xingchen rejected a request without exposing its response body."""


class XingchenRateLimitError(XingchenError):
    """Xingchen temporarily limited requests."""


class XingchenTransportError(XingchenError):
    """Xingchen could not be reached or returned malformed data."""


class _HttpResponse(Protocol):
    def read(self) -> bytes: ...

    def __enter__(self) -> "_HttpResponse": ...

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None: ...


Transport = Callable[[Request, float], _HttpResponse]


class XingchenModelClient:
    """Translate Agent context into Xingchen OpenAI-compatible HTTP requests."""

    def __init__(
        self,
        api_key: str,
        *,
        model: str,
        api_base: str = DEFAULT_XINGCHEN_API_BASE,
        timeout_seconds: float = 60.0,
        transport: Transport | None = None,
    ) -> None:
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("Xingchen API key must not be blank")
        if not isinstance(model, str) or not model.strip():
            raise ValueError(
                "Xingchen model ID must not be blank; copy the modelId from the Xingchen service list"
            )
        if timeout_seconds <= 0:
            raise ValueError("Xingchen timeout_seconds must be positive")
        self._api_key = api_key.strip()
        self._model = model.strip()
        self._api_base = self._normalize_api_base(api_base)
        self._timeout_seconds = timeout_seconds
        self._transport = transport or self._urlopen

    def complete(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[Tool],
    ) -> ModelResponse:
        """Request a non-streaming structured response without exposing credentials."""

        request_payload = {
            "model": self._model,
            "messages": [{"role": "user", "content": build_agent_prompt(messages, tools)}],
            "stream": False,
        }
        request = Request(
            f"{self._api_base}/chat/completions",
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
                raise XingchenRateLimitError(
                    "Xingchen rate limit or quota was reached; wait or check the service plan."
                ) from error
            if error.code in {401, 403}:
                raise XingchenApiError(
                    "Xingchen authentication or model authorization was rejected; verify the API key and model ID."
                ) from error
            raise XingchenApiError(
                "Xingchen API rejected the request; verify the model ID, API base, and service status."
            ) from error
        except (TimeoutError, URLError, OSError) as error:
            raise XingchenTransportError(
                "Could not reach Xingchen; check network access and try again."
            ) from error

        try:
            response_payload = json.loads(response_bytes.decode("utf-8"))
            content = response_payload["choices"][0]["message"]["content"]
        except (UnicodeDecodeError, TypeError, KeyError, IndexError, json.JSONDecodeError) as error:
            raise XingchenTransportError(
                "Xingchen returned an unexpected response format; try again later."
            ) from error
        if not isinstance(content, str):
            raise XingchenTransportError("Xingchen returned an empty or invalid message content.")
        return parse_agent_response(
            content,
            {tool.name for tool in tools},
            error_factory=XingchenApiError,
            provider_name="Xingchen",
        )

    @staticmethod
    def _normalize_api_base(api_base: str) -> str:
        normalized = api_base.strip() if isinstance(api_base, str) else ""
        parsed = urlsplit(normalized)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Xingchen API base must be an absolute HTTP(S) URL without query or fragment")
        return normalized.rstrip("/")

    @staticmethod
    def _urlopen(request: Request, timeout_seconds: float) -> _HttpResponse:
        return urlopen(request, timeout=timeout_seconds)  # noqa: S310 - operator-controlled API base
