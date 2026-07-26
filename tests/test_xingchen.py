from __future__ import annotations

import json
from urllib.error import HTTPError
import unittest

from ai_agent.messages import ChatMessage, MessageRole
from ai_agent.providers.xingchen import (
    DEFAULT_XINGCHEN_API_BASE,
    XingchenApiError,
    XingchenModelClient,
    XingchenRateLimitError,
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


class XingchenModelClientTests(unittest.TestCase):
    def test_sends_documented_v2_openai_compatible_request(self) -> None:
        transport = CapturingTransport(
            {"choices": [{"message": {"content": '{"text":"research summary","tool_calls":[]}'}}]}
        )
        client = XingchenModelClient(
            "test-secret-not-to-log",
            model="service-model-id",
            timeout_seconds=15,
            transport=transport,
        )

        response = client.complete(
            [ChatMessage(MessageRole.SYSTEM, "research only"), ChatMessage(MessageRole.USER, "summarize")],
            (create_echo_tool(),),
        )

        self.assertEqual(response.text, "research summary")
        assert transport.request is not None
        self.assertEqual(
            transport.request.full_url,
            f"{DEFAULT_XINGCHEN_API_BASE}/chat/completions",
        )
        self.assertEqual(transport.request.get_header("Authorization"), "Bearer test-secret-not-to-log")
        self.assertEqual(transport.timeout, 15)
        request_body = json.loads(transport.request.data.decode("utf-8"))
        self.assertEqual(request_body["model"], "service-model-id")
        self.assertEqual(request_body["stream"], False)
        self.assertIn('"name": "echo"', request_body["messages"][0]["content"])

    def test_accepts_tool_envelope_and_legacy_api_base(self) -> None:
        transport = CapturingTransport(
            {
                "choices": [
                    {
                        "message": {
                            "content": '{"text":"fetch first","tool_calls":[{"id":"call-1","name":"echo","arguments_json":"{\\"text\\": \\"input\\"}"}]}'
                        }
                    }
                ]
            }
        )
        client = XingchenModelClient(
            "test-secret-not-to-log",
            model="service-model-id",
            api_base="http://maas-api.cn-huabei-1.xf-yun.com/v1/",
            transport=transport,
        )

        response = client.complete([ChatMessage(MessageRole.USER, "use a tool")], (create_echo_tool(),))

        self.assertEqual(response.tool_calls[0].arguments, {"text": "input"})
        assert transport.request is not None
        self.assertEqual(
            transport.request.full_url,
            "http://maas-api.cn-huabei-1.xf-yun.com/v1/chat/completions",
        )

    def test_errors_are_safe_and_model_id_is_required(self) -> None:
        secret = "test-secret-not-to-log"

        def unauthorized_transport(request: object, timeout: float) -> FakeResponse:
            raise HTTPError("https://example.invalid", 403, "Forbidden", {}, None)

        client = XingchenModelClient(secret, model="service-model-id", transport=unauthorized_transport)
        with self.assertRaises(XingchenApiError) as unauthorized:
            client.complete([ChatMessage(MessageRole.USER, "x")], ())
        self.assertNotIn(secret, str(unauthorized.exception))
        self.assertIn("authorization", str(unauthorized.exception).lower())

        def rate_limit_transport(request: object, timeout: float) -> FakeResponse:
            raise HTTPError("https://example.invalid", 429, "Too Many Requests", {}, None)

        rate_limited = XingchenModelClient(secret, model="service-model-id", transport=rate_limit_transport)
        with self.assertRaises(XingchenRateLimitError):
            rate_limited.complete([ChatMessage(MessageRole.USER, "x")], ())

        with self.assertRaises(ValueError):
            XingchenModelClient(secret, model="")
        with self.assertRaises(ValueError):
            XingchenModelClient(secret, model="service-model-id", api_base="not-a-url")


if __name__ == "__main__":
    unittest.main()
