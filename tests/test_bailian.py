from __future__ import annotations

import json
import unittest
from urllib.error import HTTPError

from ai_agent.messages import ChatMessage, MessageRole
from ai_agent.providers.bailian import (
    BAILIAN_BEIJING_URL_TEMPLATE,
    DEFAULT_BAILIAN_MODEL,
    BailianApiError,
    BailianModelClient,
    BailianRateLimitError,
    bailian_chat_completions_url,
)
from ai_agent.tools import create_echo_tool


class FakeResponse:
    def __init__(self, payload: object) -> None:
        self._body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        return None


class CapturingTransport:
    def __init__(self, payload: object) -> None:
        self._response = FakeResponse(payload)
        self.request = None
        self.timeout = None

    def __call__(self, request: object, timeout: float) -> FakeResponse:
        self.request = request
        self.timeout = timeout
        return self._response


class BailianModelClientTests(unittest.TestCase):
    def test_builds_workspace_scoped_openai_request(self) -> None:
        transport = CapturingTransport(
            {"choices": [{"message": {"content": '{"text":"summary","tool_calls":[]}'}}]}
        )
        client = BailianModelClient(
            "test-secret-not-to-log",
            workspace_id="6432087",
            timeout_seconds=12,
            transport=transport,
        )

        response = client.complete(
            [ChatMessage(MessageRole.SYSTEM, "research only"), ChatMessage(MessageRole.USER, "summarize")],
            (create_echo_tool(),),
        )

        self.assertEqual(response.text, "summary")
        assert transport.request is not None
        self.assertEqual(
            transport.request.full_url,
            BAILIAN_BEIJING_URL_TEMPLATE.format(workspace_id="6432087"),
        )
        self.assertEqual(transport.request.get_header("Authorization"), "Bearer test-secret-not-to-log")
        request_body = json.loads(transport.request.data.decode("utf-8"))
        self.assertEqual(request_body["model"], DEFAULT_BAILIAN_MODEL)
        self.assertFalse(request_body["stream"])
        self.assertIn("research only", request_body["messages"][0]["content"])

    def test_empty_workspace_uses_official_compatible_endpoint(self) -> None:
        self.assertEqual(
            bailian_chat_completions_url(),
            "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        )

    def test_explicit_https_base_url_overrides_workspace_endpoint(self) -> None:
        transport = CapturingTransport(
            {"choices": [{"message": {"content": '{"text":"ok","tool_calls":[]}'}}]}
        )
        client = BailianModelClient(
            "test-secret-not-to-log",
            workspace_id="6432087",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
            transport=transport,
        )

        client.complete([ChatMessage(MessageRole.USER, "test")], ())

        assert transport.request is not None
        self.assertEqual(
            transport.request.full_url,
            "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        )

    def test_explicit_base_url_must_use_https(self) -> None:
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            BailianModelClient(
                "test-secret-not-to-log",
                base_url="http://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
            )

    def test_http_errors_are_safe_and_rate_limit_is_distinguished(self) -> None:
        secret = "test-secret-not-to-log"

        def unauthorized_transport(request: object, timeout: float) -> FakeResponse:
            raise HTTPError("https://example.invalid", 401, "Unauthorized", {}, None)

        with self.assertRaises(BailianApiError) as unauthorized:
            BailianModelClient(secret, transport=unauthorized_transport).complete(
                [ChatMessage(MessageRole.USER, "x")], ()
            )
        self.assertNotIn(secret, str(unauthorized.exception))
        self.assertIn("authentication", str(unauthorized.exception).lower())

        def rate_limit_transport(request: object, timeout: float) -> FakeResponse:
            raise HTTPError("https://example.invalid", 429, "Too Many Requests", {}, None)

        with self.assertRaises(BailianRateLimitError):
            BailianModelClient(secret, transport=rate_limit_transport).complete(
                [ChatMessage(MessageRole.USER, "x")], ()
            )

    def test_disabled_provider_does_not_call_transport(self) -> None:
        transport = CapturingTransport({"choices": []})
        client = BailianModelClient("test-secret-not-to-log", transport=transport, enabled=lambda: False)

        with self.assertRaisesRegex(BailianApiError, "disabled in parameter settings"):
            client.complete([ChatMessage(MessageRole.USER, "x")], ())

        self.assertIsNone(transport.request)


if __name__ == "__main__":
    unittest.main()
