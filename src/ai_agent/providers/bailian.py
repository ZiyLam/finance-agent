"""Alibaba Cloud Bailian (Model Studio) OpenAI-compatible adapter.

The Beijing endpoint is scoped to the user's business space when a workspace
ID is supplied.  Credentials are accepted only at construction time and are
never included in errors, prompts, or logs.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from ..messages import ChatMessage, ModelResponse
from ..tools import Tool
from .structured_response import build_agent_prompt, parse_agent_response

BAILIAN_CHAT_COMPLETIONS_URL = (
    "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
)
BAILIAN_BEIJING_URL_TEMPLATE = (
    "https://{workspace_id}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/chat/completions"
)
DEFAULT_BAILIAN_MODEL = "qwen-plus"
_WORKSPACE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


class BailianError(RuntimeError):
    """Base class for safe, user-facing Bailian provider errors."""


class BailianApiError(BailianError):
    """The Bailian API rejected a request without exposing its response body."""


class BailianRateLimitError(BailianError):
    """Bailian temporarily limited requests."""


class BailianTransportError(BailianError):
    """The Bailian API could not be reached or returned malformed data."""


class _HttpResponse(Protocol):
    def read(self) -> bytes: ...

    def __enter__(self) -> "_HttpResponse": ...

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None: ...


Transport = Callable[[Request, float], _HttpResponse]


def bailian_chat_completions_url(workspace_id: str = "") -> str:
    """Return the fixed HTTPS endpoint, scoped to a business workspace when set."""

    workspace_id = workspace_id.strip()
    if not workspace_id:
        return BAILIAN_CHAT_COMPLETIONS_URL
    if not _WORKSPACE_ID_PATTERN.fullmatch(workspace_id):
        raise ValueError("Bailian workspace_id contains invalid characters")
    return BAILIAN_BEIJING_URL_TEMPLATE.format(workspace_id=workspace_id)


class BailianModelClient:
    """Translate Agent context into Bailian requests and normalized responses."""

    def __init__(
        self,
        api_key: str,
        *,
        model: str = DEFAULT_BAILIAN_MODEL,
        workspace_id: str = "",
        base_url: str | None = None,
        timeout_seconds: float = 60.0,
        transport: Transport | None = None,
        enabled: Callable[[], bool] | None = None,
    ) -> None:
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("Bailian API key must not be blank")
        if not isinstance(model, str) or not model.strip():
            raise ValueError("Bailian model must not be blank")
        if timeout_seconds <= 0:
            raise ValueError("Bailian timeout_seconds must be positive")
        resolved_url = base_url.strip() if isinstance(base_url, str) else ""
        if resolved_url:
            parsed = urlparse(resolved_url)
            if parsed.scheme != "https" or not parsed.netloc:
                raise ValueError("Bailian base_url must be an HTTPS URL")
        else:
            resolved_url = bailian_chat_completions_url(workspace_id)
        self._api_key = api_key.strip()
        self._model = model.strip()
        self._timeout_seconds = timeout_seconds
        self._url = resolved_url
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
            raise BailianApiError("Bailian is disabled in parameter settings.")

        request_payload = {
            "model": self._model,
            "messages": [{"role": "user", "content": self._build_prompt(messages, tools)}],
            "stream": False,
        }
        request = Request(
            self._url,
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
                raise BailianRateLimitError(
                    "Bailian rate limit reached; wait briefly and try again."
                ) from error
            if error.code in {401, 403}:
                raise BailianApiError(
                    "Bailian authentication was rejected; update BAILIAN_API_KEY or workspace access."
                ) from error
            raise BailianApiError(
                "Bailian API rejected the request; verify model access and request limits."
            ) from error
        except (TimeoutError, URLError, OSError) as error:
            raise BailianTransportError(
                "Could not reach Bailian; check network access and try again."
            ) from error

        try:
            response_payload = json.loads(response_bytes.decode("utf-8"))
            content = response_payload["choices"][0]["message"]["content"]
        except (UnicodeDecodeError, TypeError, KeyError, IndexError, json.JSONDecodeError) as error:
            raise BailianTransportError(
                "Bailian returned an unexpected response format; try again later."
            ) from error
        if not isinstance(content, str):
            raise BailianTransportError("Bailian returned an empty or invalid message content.")
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
            error_factory=BailianApiError,
            provider_name="Bailian",
        )
