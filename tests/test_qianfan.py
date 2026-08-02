from __future__ import annotations

import json
import unittest
from urllib.error import HTTPError

from ai_agent.messages import ChatMessage, MessageRole
from ai_agent.providers.qianfan import (
    DEFAULT_QIANFAN_MODEL,
    QIANFAN_CHAT_COMPLETIONS_URL,
    QianfanApiError,
    QianfanModelClient,
    QianfanRateLimitError,
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


class QianfanModelClientTests(unittest.TestCase):
    def test_sends_openai_compatible_request_and_parses_final_text(self) -> None:
        transport = CapturingTransport(
            {"choices": [{"message": {"content": '{"text":"research summary","tool_calls":[]}'}}]}
        )
        client = QianfanModelClient(
            "test-secret-not-to-log",
            timeout_seconds=12,
            transport=transport,
        )

        response = client.complete(
            [ChatMessage(MessageRole.SYSTEM, "research only"), ChatMessage(MessageRole.USER, "summarize")],
            (create_echo_tool(),),
        )

        self.assertEqual(response.text, "research summary")
        self.assertEqual(response.tool_calls, ())
        assert transport.request is not None
        self.assertEqual(transport.request.full_url, QIANFAN_CHAT_COMPLETIONS_URL)
        self.assertEqual(transport.request.get_header("Authorization"), "Bearer test-secret-not-to-log")
        self.assertEqual(transport.timeout, 12)
        request_body = json.loads(transport.request.data.decode("utf-8"))
        self.assertEqual(request_body["model"], DEFAULT_QIANFAN_MODEL)
        self.assertEqual(request_body["stream"], False)
        self.assertEqual(request_body["messages"][0]["role"], "user")
        self.assertIn("research only", request_body["messages"][0]["content"])
        self.assertIn('"name": "echo"', request_body["messages"][0]["content"])

    def test_accepts_json_fence_and_normalizes_local_tool_calls(self) -> None:
        transport = CapturingTransport(
            {
                "choices": [
                    {
                        "message": {
                            "content": "```json\n{\"text\":\"fetch first\",\"tool_calls\":[{\"id\":\"call-1\",\"name\":\"echo\",\"arguments_json\":\"{\\\"text\\\": \\\"input\\\"}\"}]}\n```"
                        }
                    }
                ]
            }
        )
        client = QianfanModelClient("test-secret-not-to-log", transport=transport)

        response = client.complete([ChatMessage(MessageRole.USER, "use a tool")], (create_echo_tool(),))

        self.assertEqual(response.text, "fetch first")
        self.assertEqual(response.tool_calls[0].name, "echo")
        self.assertEqual(response.tool_calls[0].arguments, {"text": "input"})

    def test_http_errors_are_safe_and_rate_limit_is_distinguished(self) -> None:
        secret = "test-secret-not-to-log"

        def unauthorized_transport(request: object, timeout: float) -> FakeResponse:
            raise HTTPError("https://example.invalid", 401, "Unauthorized", {}, None)

        client = QianfanModelClient(secret, transport=unauthorized_transport)
        with self.assertRaises(QianfanApiError) as unauthorized:
            client.complete([ChatMessage(MessageRole.USER, "x")], ())
        self.assertNotIn(secret, str(unauthorized.exception))
        self.assertIn("authentication", str(unauthorized.exception).lower())

        def rate_limit_transport(request: object, timeout: float) -> FakeResponse:
            raise HTTPError("https://example.invalid", 429, "Too Many Requests", {}, None)

        rate_limited = QianfanModelClient(secret, transport=rate_limit_transport)
        with self.assertRaises(QianfanRateLimitError) as rate_limit:
            rate_limited.complete([ChatMessage(MessageRole.USER, "x")], ())
        self.assertNotIn(secret, str(rate_limit.exception))

    def test_rejects_non_structured_content(self) -> None:
        client = QianfanModelClient(
            "test-secret-not-to-log",
            transport=CapturingTransport({"choices": [{"message": {"content": "plain text"}}]}),
        )

        with self.assertRaises(QianfanApiError):
            client.complete([ChatMessage(MessageRole.USER, "x")], ())

    def test_disabled_provider_does_not_call_transport(self) -> None:
        transport = CapturingTransport({"choices": []})
        client = QianfanModelClient(
            "test-secret-not-to-log",
            transport=transport,
            enabled=lambda: False,
        )

        with self.assertRaisesRegex(QianfanApiError, "disabled in parameter settings"):
            client.complete([ChatMessage(MessageRole.USER, "x")], ())

        self.assertIsNone(transport.request)


if __name__ == "__main__":
    unittest.main()
