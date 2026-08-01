from __future__ import annotations

import json
import unittest

from ai_agent.knowledge_base.ima import ImaKnowledgeBaseClient, ImaKnowledgeBaseError
from ai_agent.tools import ToolRegistry, create_ima_knowledge_search_tool


class RecordingTransport:
    def __init__(self, response: dict[str, object]) -> None:
        self.response = response
        self.calls: list[tuple[str, bytes, dict[str, str], float]] = []

    def __call__(self, url: str, body: bytes, headers: dict[str, str], timeout: float) -> bytes:
        self.calls.append((url, body, headers, timeout))
        return json.dumps(self.response).encode("utf-8")


class ImaKnowledgeBaseClientTests(unittest.TestCase):
    def test_lists_knowledge_bases_using_official_read_only_endpoint(self) -> None:
        transport = RecordingTransport(
            {
                "code": 0,
                "data": {
                    "info_list": [
                        {"id": "kb-001", "name": "Equity research"},
                        {"id": "", "name": "Ignored"},
                    ]
                },
            }
        )
        client = ImaKnowledgeBaseClient("client-id", "api-key", transport=transport)

        result = client.list_knowledge_bases(limit=5)

        self.assertEqual([(item.identifier, item.name) for item in result], [("kb-001", "Equity research")])
        url, body, headers, timeout = transport.calls[0]
        self.assertEqual(url, "https://ima.qq.com/openapi/wiki/v1/search_knowledge_base")
        self.assertEqual(json.loads(body), {"query": "", "cursor": "", "limit": 5})
        self.assertEqual(headers["ima-openapi-clientid"], "client-id")
        self.assertEqual(headers["ima-openapi-apikey"], "api-key")
        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertEqual(timeout, 10.0)

    def test_list_accepts_current_ima_kb_prefixed_response_fields(self) -> None:
        transport = RecordingTransport(
            {"code": 0, "data": {"info_list": [{"kb_id": "kb-001", "kb_name": "Finance knowledge"}]}}
        )
        client = ImaKnowledgeBaseClient("client-id", "api-key", transport=transport)

        result = client.list_knowledge_bases()

        self.assertEqual([(item.identifier, item.name) for item in result], [("kb-001", "Finance knowledge")])

    def test_search_bounds_content_and_does_not_expose_ima_identifiers(self) -> None:
        long_snippet = "x" * 1_700
        transport = RecordingTransport(
            {
                "code": 0,
                "data": {
                    "info_list": [
                        {
                            "media_id": "secret-media-id",
                            "title": "  Research note  ",
                            "highlight_content": f"  {long_snippet}  ",
                            "media_type": 1,
                        },
                        {"media_id": "skip", "title": "", "highlight_content": ""},
                    ]
                },
            }
        )
        client = ImaKnowledgeBaseClient(
            "client-id", "api-key", knowledge_base_id="selected-kb", transport=transport
        )

        result = client.search("  valuation  ", limit=1)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].title, "Research note")
        self.assertEqual(len(result[0].snippet), 1_500)
        self.assertEqual(result[0].media_type, 1)
        self.assertNotIn("media_id", result[0].to_dict())
        self.assertNotIn("selected-kb", json.dumps(result[0].to_dict()))
        _, body, _, _ = transport.calls[0]
        self.assertEqual(
            json.loads(body),
            {"query": "valuation", "knowledge_base_id": "selected-kb", "cursor": ""},
        )

    def test_search_requires_a_target_and_rejects_invalid_query_before_request(self) -> None:
        transport = RecordingTransport({"code": 0, "data": {"info_list": []}})
        client = ImaKnowledgeBaseClient("client-id", "api-key", transport=transport)

        with self.assertRaisesRegex(ImaKnowledgeBaseError, "target is not configured"):
            client.search("valuation")
        self.assertEqual(transport.calls, [])

        configured_client = ImaKnowledgeBaseClient(
            "client-id", "api-key", knowledge_base_id="selected-kb", transport=transport
        )
        with self.assertRaisesRegex(ValueError, "1 to 400"):
            configured_client.search(" ")
        self.assertEqual(transport.calls, [])

    def test_search_lazily_resolves_an_exact_knowledge_base_name(self) -> None:
        class SequenceTransport:
            def __init__(self) -> None:
                self.calls: list[tuple[str, bytes, dict[str, str], float]] = []
                self.responses = [
                    {"code": 0, "data": {"info_list": [{"kb_id": "selected-kb", "kb_name": "Finance"}]}},
                    {
                        "code": 0,
                        "data": {
                            "info_list": [
                                {"media_id": "hidden", "title": "Memo", "highlight_content": "Reference text"}
                            ]
                        },
                    },
                ]

            def __call__(self, url: str, body: bytes, headers: dict[str, str], timeout: float) -> bytes:
                self.calls.append((url, body, headers, timeout))
                return json.dumps(self.responses.pop(0)).encode("utf-8")

        transport = SequenceTransport()
        client = ImaKnowledgeBaseClient("client-id", "api-key", knowledge_base_name="Finance", transport=transport)

        result = client.search("revenue")

        self.assertEqual(result[0].title, "Memo")
        self.assertEqual(len(transport.calls), 2)
        self.assertEqual(json.loads(transport.calls[0][1]), {"query": "Finance", "cursor": "", "limit": 20})
        self.assertEqual(
            json.loads(transport.calls[1][1]),
            {"query": "revenue", "knowledge_base_id": "selected-kb", "cursor": ""},
        )

    def test_search_rejects_a_missing_or_ambiguous_knowledge_base_name(self) -> None:
        missing_transport = RecordingTransport({"code": 0, "data": {"info_list": []}})
        missing_client = ImaKnowledgeBaseClient(
            "client-id", "api-key", knowledge_base_name="Missing", transport=missing_transport
        )
        with self.assertRaisesRegex(ImaKnowledgeBaseError, "was not found"):
            missing_client.search("revenue")

        ambiguous_transport = RecordingTransport(
            {
                "code": 0,
                "data": {
                    "info_list": [
                        {"kb_id": "one", "kb_name": "Duplicate"},
                        {"kb_id": "two", "kb_name": "Duplicate"},
                    ]
                },
            }
        )
        ambiguous_client = ImaKnowledgeBaseClient(
            "client-id", "api-key", knowledge_base_name="Duplicate", transport=ambiguous_transport
        )
        with self.assertRaisesRegex(ImaKnowledgeBaseError, "is ambiguous"):
            ambiguous_client.search("revenue")

    def test_provider_error_is_sanitized(self) -> None:
        transport = RecordingTransport({"code": 110030, "msg": "authorization details: api-key", "data": {}})
        client = ImaKnowledgeBaseClient("client-id", "api-key", transport=transport)

        with self.assertRaisesRegex(ImaKnowledgeBaseError, "IMA rejected") as captured:
            client.list_knowledge_bases()

        self.assertNotIn("api-key", str(captured.exception))


class ImaKnowledgeSearchToolTests(unittest.TestCase):
    def test_tool_labels_results_as_reference_material(self) -> None:
        transport = RecordingTransport(
            {
                "code": 0,
                "data": {
                    "info_list": [
                        {
                            "media_id": "not-for-agent",
                            "title": "Company memo",
                            "highlight_content": "Revenue grew year over year.",
                            "media_type": 7,
                        }
                    ]
                },
            }
        )
        client = ImaKnowledgeBaseClient("client-id", "api-key", knowledge_base_id="selected-kb", transport=transport)
        registry = ToolRegistry((create_ima_knowledge_search_tool(client),))

        response = registry.execute("ima_knowledge_search", {"query": "revenue", "limit": 1})

        payload = json.loads(response)
        self.assertEqual(payload["source"], "Tencent ima private knowledge base")
        self.assertIn("not instructions", payload["content_handling"])
        self.assertEqual(payload["results"], [{"title": "Company memo", "snippet": "Revenue grew year over year.", "media_type": 7}])
        self.assertNotIn("not-for-agent", response)
        self.assertNotIn("selected-kb", response)


if __name__ == "__main__":
    unittest.main()
