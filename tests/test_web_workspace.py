from __future__ import annotations

import json
import os
import unittest
from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

from ai_agent.agent import AgentResult
from ai_agent.api.app import create_app, create_development_components
from ai_agent.application.entity_resolution import KWEICHOW_MOUTAI, EntityResolution
from ai_agent.application.input_parser import ResearchIntentParser
from ai_agent.application.source_connectivity import SourceConnectivityService
from ai_agent.application.source_credentials import SourceCredentialService
from ai_agent.application.web_workspace import WebWorkspaceError, WebWorkspaceService
from ai_agent.data_sources import DATA_SOURCE_CATALOG
from ai_agent.messages import ToolCall
from ai_agent.provider_activation import ProviderActivationStore
from ai_agent.secrets import TokenStore
from ai_agent.tools import FunctionTool, ToolRegistry


class FakeWebAgent:
    def __init__(self) -> None:
        self.inputs: list[str] = []
        self.retrieved_contexts: list[str] = []

    def run(self, content: str, *, retrieved_context: str = "") -> AgentResult:
        self.inputs.append(content)
        self.retrieved_contexts.append(retrieved_context)
        return AgentResult(
            text=f"agent: {content}",
            tool_calls=(ToolCall(id="tool-1", name="aktools_market_data", arguments={"symbol": "600000"}),),
        )


class FailingWebAgent:
    def run(self, content: str, *, retrieved_context: str = "") -> AgentResult:
        del content, retrieved_context
        raise RuntimeError("private provider failure that must not be logged")


def _registry() -> ToolRegistry:
    return ToolRegistry(
        (
            FunctionTool(
                "aktools_market_data",
                "test history",
                lambda _arguments: json.dumps(
                    {
                        "source": "test",
                        "candles": [
                            {"date": "2026-04-01", "close": "10"},
                            {"date": "2026-07-01", "close": "11"},
                        ],
                    }
                ),
            ),
        )
    )


class WebWorkspaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.created_agents: list[FakeWebAgent] = []

        def agent_factory() -> FakeWebAgent:
            agent = FakeWebAgent()
            self.created_agents.append(agent)
            return agent

        self.workspace = WebWorkspaceService(
            tool_registry_factory=_registry,
            agent_factory=agent_factory,  # type: ignore[arg-type]
            model_provider="codex",
        )
        components = create_development_components(
            tool_registry_factory=_registry,
            session_secret="test-session-secret-with-at-least-thirty-two-characters",
        )
        token_store = TokenStore(
            Path(self.temporary_directory.name) / "tokens.json",
            protect=lambda value: value[::-1],
            unprotect=lambda value: value[::-1],
        )
        self.provider_activation_path = Path(self.temporary_directory.name) / "provider-settings.json"
        self.provider_activation = ProviderActivationStore(self.provider_activation_path)
        self.source_credentials = SourceCredentialService(
            token_store,
            activation=self.provider_activation,
        )
        self.source_connectivity = SourceConnectivityService(
            token_store,
            activation=self.provider_activation,
            probes={
                "eastmoney": lambda _token: (_ for _ in ()).throw(
                    RuntimeError("private upstream failure detail")
                )
            },
        )
        self.app = create_app(
            components,
            web_workspace=self.workspace,
            source_credentials=self.source_credentials,
            source_connectivity=self.source_connectivity,
        )
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_web_status_and_static_entry_do_not_expose_credentials(self) -> None:
        status = self.client.get("/v1/web/status")
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["agent_framework"], "langchain")
        self.assertEqual(status.json()["language_enhancement"], "lcel_rag")
        self.assertEqual(status.json()["configured_tools"], ["aktools_market_data"])
        professional = status.json()["professional_research"]
        self.assertEqual(
            [market["key"] for market in professional["markets"]],
            ["a_share", "hong_kong", "us", "japan", "europe"],
        )
        self.assertEqual(len(professional["indices"]), 18)
        self.assertEqual(professional["maximum_indices"], 6)
        self.assertRegex(status.headers["x-request-id"], r"^[0-9a-f]{32}$")
        page = self.client.get("/web/")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Finance Agent", page.text)
        self.assertIn('id="result-analysis-duration"', page.text)
        self.assertNotIn('id="result-analyzed-at"', page.text)
        self.assertIn('id="professional-mode"', page.text)
        self.assertIn('id="professional-controls"', page.text)

    def test_professional_endpoint_returns_multi_index_result_without_creating_an_agent(self) -> None:
        response = self.client.post(
            "/v1/web/professional-research",
            json={
                "conversation_id": "professional-1",
                "content": "比较大小盘风格",
                "start_date": "2026-06-01",
                "end_date": "2026-06-30",
                "markets": ["a_share"],
                "indices": ["csi_300", "csi_500"],
                "metrics": ["valuation_style", "risks"],
            },
        )

        self.assertEqual(response.status_code, 200)
        reply = response.json()
        self.assertEqual(reply["response_kind"], "professional_index_comparison")
        self.assertEqual([item["index"]["key"] for item in reply["snapshots"]], ["csi_300", "csi_500"])
        self.assertEqual(reply["research_period"]["start_date"], "2026-06-01")
        self.assertNotIn("market_data", reply["snapshots"][0])
        self.assertEqual(self.created_agents, [])

    def test_professional_endpoint_rejects_index_outside_selected_markets(self) -> None:
        response = self.client.post(
            "/v1/web/professional-research",
            json={
                "conversation_id": "professional-1",
                "content": "",
                "start_date": "2026-06-01",
                "end_date": "2026-06-30",
                "markets": ["a_share"],
                "indices": ["sp_500"],
                "metrics": ["risks"],
            },
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"], "Every selected index must belong to a selected market")

    def test_chat_reuses_a_conversation_scoped_agent_and_returns_tool_metadata(self) -> None:
        first = self.client.post("/v1/web/chat", json={"conversation_id": "personal-1", "content": "first"})
        second = self.client.post("/v1/web/chat", json={"conversation_id": "personal-1", "content": "second"})

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["tool_calls"][0]["name"], "aktools_market_data")
        completed_at = datetime.fromisoformat(first.json()["analysis_completed_at"])
        self.assertIsNotNone(completed_at.tzinfo)
        self.assertEqual(second.json()["text"], "agent: second")
        self.assertEqual(first.json()["language_context"]["framework"], "lcel_rag")
        self.assertEqual(len(self.created_agents), 1)
        self.assertEqual(self.created_agents[0].inputs, ["first", "second"])
        self.assertTrue(self.created_agents[0].retrieved_contexts[0])

    def test_idle_agent_session_expires_and_is_recreated(self) -> None:
        clock = [100.0]
        created_agents: list[FakeWebAgent] = []

        def agent_factory() -> FakeWebAgent:
            agent = FakeWebAgent()
            created_agents.append(agent)
            return agent

        workspace = WebWorkspaceService(
            tool_registry_factory=_registry,
            agent_factory=agent_factory,  # type: ignore[arg-type]
            model_provider="codex",
            session_ttl_seconds=60,
            clock=lambda: clock[0],
        )

        workspace.chat(conversation_id="expiring", content="first")
        clock[0] += 59
        workspace.chat(conversation_id="expiring", content="second")
        clock[0] += 61
        workspace.chat(conversation_id="expiring", content="third")

        self.assertEqual(len(created_agents), 2)
        self.assertEqual(created_agents[0].inputs, ["first", "second"])
        self.assertEqual(created_agents[1].inputs, ["third"])

    def test_agent_receives_the_resolved_time_window_and_the_web_reply_exposes_it(self) -> None:
        created_agents: list[FakeWebAgent] = []

        def agent_factory() -> FakeWebAgent:
            agent = FakeWebAgent()
            created_agents.append(agent)
            return agent

        workspace = WebWorkspaceService(
            tool_registry_factory=_registry,
            agent_factory=agent_factory,  # type: ignore[arg-type]
            model_provider="codex",
            intent_parser=ResearchIntentParser(today=lambda: date(2026, 7, 27)),
        )

        reply = workspace.chat(conversation_id="dated", content="分析 600519 近期走势")

        self.assertEqual(reply.research_period["start_date"], "2026-06-27")  # type: ignore[index]
        self.assertEqual(reply.research_period["end_date"], "2026-07-27")  # type: ignore[index]
        self.assertIn("start_date=2026-06-27; end_date=2026-07-27", created_agents[0].retrieved_contexts[0])

    def test_index_request_returns_a_complete_snapshot_without_creating_an_agent(self) -> None:
        calls: list[str] = []

        def market_data(_arguments: object) -> str:
            calls.append("yfinance_market_data")
            return json.dumps(
                {
                    "source": "test index source",
                    "candles": [
                        {"date": "2026-07-21", "close": "5000", "high": "5010", "low": "4990"},
                        {"date": "2026-07-22", "close": "5015", "high": "5020", "low": "5000"},
                    ],
                }
            )

        def registry_factory() -> ToolRegistry:
            return ToolRegistry(
                (FunctionTool("yfinance_market_data", "index test", market_data),)
            )
        workspace = WebWorkspaceService(
            tool_registry_factory=registry_factory,
            agent_factory=FakeWebAgent,  # type: ignore[arg-type]
            model_provider="echo",
        )

        with patch("ai_agent.application.web_workspace.log_event") as logged:
            reply = workspace.chat(conversation_id="index", content="中证500")

        self.assertEqual(reply.response_kind, "index_snapshot")
        self.assertEqual(reply.snapshot["index"]["symbol"], "000905")  # type: ignore[index]
        self.assertEqual(calls, ["yfinance_market_data"])
        self.assertGreaterEqual(reply.analysis_duration_ms, 0)
        events = [call.args[0] for call in logged.call_args_list]
        self.assertIn("rag_retrieval_completed", events)
        self.assertIn("index_research_started", events)
        self.assertIn("index_research_completed", events)
        completed = next(call for call in logged.call_args_list if call.args[0] == "web_chat_completed")
        self.assertEqual(completed.kwargs["duration_ms"], reply.analysis_duration_ms)

    def test_lru_eviction_bounds_idle_conversation_agents(self) -> None:
        clock = [0.0]
        created_agents: list[FakeWebAgent] = []

        def agent_factory() -> FakeWebAgent:
            agent = FakeWebAgent()
            created_agents.append(agent)
            return agent

        workspace = WebWorkspaceService(
            tool_registry_factory=_registry,
            agent_factory=agent_factory,  # type: ignore[arg-type]
            model_provider="codex",
            session_ttl_seconds=3_600,
            max_conversations=2,
            clock=lambda: clock[0],
        )

        workspace.chat(conversation_id="first", content="first")
        clock[0] += 1
        workspace.chat(conversation_id="second", content="second")
        clock[0] += 1
        workspace.chat(conversation_id="first", content="third")
        clock[0] += 1
        workspace.chat(conversation_id="third", content="fourth")
        clock[0] += 1
        workspace.chat(conversation_id="second", content="fifth")

        self.assertEqual(len(created_agents), 4)
        self.assertEqual(created_agents[0].inputs, ["first", "third"])
        self.assertEqual(created_agents[1].inputs, ["second"])
        self.assertEqual(created_agents[2].inputs, ["fourth"])
        self.assertEqual(created_agents[3].inputs, ["fifth"])

    def test_ambiguous_hsbc_name_returns_all_candidate_snapshots_without_creating_an_agent(self) -> None:
        response = self.client.post(
            "/v1/web/chat",
            json={"conversation_id": "personal-1", "content": "汇丰银行"},
        )

        self.assertEqual(response.status_code, 200)
        reply = response.json()
        self.assertEqual(reply["response_kind"], "candidate_snapshots")
        self.assertEqual(
            [(item["security"]["symbol"], item["security"]["currency"]) for item in reply["snapshots"]],
            [("0005", "HKD"), ("HSBC", "USD")],
        )
        self.assertEqual(self.created_agents, [])

    def test_explicit_hsbc_ticker_uses_the_bounded_beginner_snapshot_without_an_agent(self) -> None:
        response = self.client.post(
            "/v1/web/chat",
            json={"conversation_id": "personal-1", "content": "HSBC"},
        )

        self.assertEqual(response.status_code, 200)
        reply = response.json()
        self.assertEqual(reply["response_kind"], "beginner_snapshot")
        self.assertEqual(reply["snapshot"]["security"]["yahoo_symbol"], "HSBC")
        self.assertEqual(reply["snapshot"]["financial_reports"]["status"], "not_connected")
        self.assertEqual(self.created_agents, [])

    def test_simple_latest_price_uses_discovery_and_snapshot_without_an_agent(self) -> None:
        with patch.object(
            self.workspace._security_discovery,
            "discover",
            return_value=EntityResolution("查询 600000 最新价格", (KWEICHOW_MOUTAI,)),
        ) as discover:
            reply = self.workspace.chat(
                conversation_id="latest-price",
                content="查询 600000 最新价格",
            )

        self.assertEqual(reply.response_kind, "beginner_snapshot")
        self.assertEqual(self.created_agents, [])
        discover.assert_called_once_with("查询 600000 最新价格")

    def test_open_ended_sector_prompt_returns_a_bounded_failure_without_creating_an_agent(self) -> None:
        response = self.client.post(
            "/v1/web/chat",
            json={"conversation_id": "personal-1", "content": "近期值得关注的板块"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["response_kind"], "market_scan")
        self.assertEqual(response.json()["snapshot"]["status"], "unavailable")
        self.assertEqual(self.created_agents, [])

    def test_open_ended_sector_prompt_returns_structured_market_scan_without_an_agent(self) -> None:
        market_scan = FunctionTool(
            "eastmoney_market_scan",
            "deterministic market scan",
            lambda _arguments: json.dumps(
                {
                    "source": "test sector source",
                    "freshness": "current_or_delayed",
                    "market_sentiment": {
                        "label": "结构性分化",
                        "leader_average_change_percent": 2.1,
                        "laggard_average_change_percent": -1.2,
                    },
                    "leading_industries": [{"code": "BK1", "name": "测试领涨", "change_percent": 2.3}],
                    "lagging_industries": [{"code": "BK2", "name": "测试落后", "change_percent": -1.4}],
                },
                ensure_ascii=False,
            ),
        )
        workspace = WebWorkspaceService(
            tool_registry_factory=lambda: ToolRegistry((market_scan,)),
            agent_factory=FakeWebAgent,  # type: ignore[arg-type]
            model_provider="echo",
            intent_parser=ResearchIntentParser(today=lambda: date(2026, 8, 1)),
        )

        reply = workspace.chat(conversation_id="sector", content="我想了解近期哪些板块值得关注")

        self.assertEqual(reply.response_kind, "market_scan")
        self.assertEqual(reply.snapshot["status"], "complete")  # type: ignore[index]
        self.assertEqual(reply.snapshot["market_sentiment"]["label"], "结构性分化")  # type: ignore[index]
        self.assertEqual(reply.research_period["start_date"], "2026-07-02")  # type: ignore[index]
        self.assertEqual(reply.research_period["end_date"], "2026-08-01")  # type: ignore[index]

    def test_web_content_is_bounded_before_retrieval_or_agent_execution(self) -> None:
        response = self.client.post(
            "/v1/web/chat",
            json={"conversation_id": "personal-1", "content": "x" * 4_001},
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"], "content must not exceed 4,000 characters")
        self.assertEqual(self.created_agents, [])

    def test_agent_failure_emits_a_safe_diagnostic_event_without_request_content(self) -> None:
        workspace = WebWorkspaceService(
            tool_registry_factory=_registry,
            agent_factory=FailingWebAgent,  # type: ignore[arg-type]
            model_provider="codex",
        )

        with self.assertLogs("finance_agent", level="ERROR") as captured:
            with self.assertRaisesRegex(WebWorkspaceError, "temporarily unavailable"):
                workspace.chat(conversation_id="diagnostics", content="private research question")

        logs = "\n".join(captured.output)
        self.assertIn("agent_invocation_failed", logs)
        self.assertNotIn("private research question", logs)
        self.assertNotIn("private provider failure", logs)

    def test_report_endpoint_uses_the_configured_data_tool_chain(self) -> None:
        response = self.client.post(
            "/v1/web/reports",
            json={
                "content": "请分析 600000 在 2026-04-01 至 2026-07-01 的历史走势",
            },
        )

        self.assertEqual(response.status_code, 200)
        report = response.json()["report"]
        self.assertEqual(report["request_status"], "complete")
        self.assertEqual(report["scope"]["symbol"], "600000")
        self.assertEqual(report["evidence"][0]["raw_tool"], "aktools_market_data")
        self.assertEqual(report["language_context"]["framework"], "lcel_rag")

    def test_report_endpoint_returns_clarifications_for_an_underspecified_request(self) -> None:
        response = self.client.post("/v1/web/reports", json={"content": "帮我研究近期走势"})

        self.assertEqual(response.status_code, 200)
        report = response.json()["report"]
        self.assertEqual(report["request_status"], "needs_clarification")
        self.assertTrue(report["clarifications"])

    def test_non_local_access_requires_an_explicit_token_when_configured(self) -> None:
        with patch.dict(os.environ, {"AGENT_WEB_ACCESS_TOKEN": "test-web-token"}, clear=False):
            denied = self.client.get("/v1/web/status")
            allowed = self.client.get("/v1/web/status", headers={"X-Finance-Agent-Token": "test-web-token"})

        self.assertEqual(denied.status_code, 401)
        self.assertEqual(allowed.status_code, 200)

    def test_source_credential_page_never_reveals_tokens(self) -> None:
        sensitive_token = "never-return-this-token"
        with patch.dict(os.environ, {"ALLTICK_API_TOKEN": ""}, clear=False):
            listed = self.client.get("/v1/web/sources")
            saved = self.client.put("/v1/web/sources/alltick/token", json={"token": sensitive_token})
            after_save = self.client.get("/v1/web/sources")
            deleted = self.client.delete("/v1/web/sources/alltick/token")

        self.assertEqual(listed.status_code, 200)
        self.assertEqual(len(listed.json()["sources"]), len(DATA_SOURCE_CATALOG))
        self.assertNotIn(sensitive_token, listed.text)
        self.assertEqual(saved.status_code, 200)
        self.assertNotIn(sensitive_token, saved.text)
        self.assertEqual(saved.json()["source"]["credential_origin"], "secure_local_store")
        alltick_status = next(item for item in after_save.json()["sources"] if item["name"] == "alltick")
        self.assertTrue(alltick_status["configured"])
        self.assertEqual(alltick_status["credential_origin"], "secure_local_store")
        self.assertNotIn("active_token", alltick_status)
        self.assertNotIn(sensitive_token, after_save.text)
        self.assertEqual(after_save.headers["cache-control"], "no-store, private")
        self.assertEqual(deleted.status_code, 200)
        self.assertTrue(deleted.json()["source"]["stored_token_deleted"])

    def test_source_status_reports_environment_configuration_without_returning_the_token(self) -> None:
        environment_token = "environment-token-must-not-display"
        with patch.dict(os.environ, {"ALLTICK_API_TOKEN": environment_token}, clear=False):
            response = self.client.get("/v1/web/sources")

        self.assertEqual(response.status_code, 200)
        alltick_status = next(item for item in response.json()["sources"] if item["name"] == "alltick")
        self.assertTrue(alltick_status["configured"])
        self.assertEqual(alltick_status["credential_origin"], "environment_variable")
        self.assertNotIn("active_token", alltick_status)
        self.assertNotIn(environment_token, response.text)

    def test_source_catalog_assigns_qianfan_to_the_llm_module(self) -> None:
        response = self.client.get("/v1/web/sources")

        self.assertEqual(response.status_code, 200)
        catalog = response.json()["sources"]
        qianfan = next(source for source in catalog if source["name"] == "qianfan")
        data_sources = [source for source in catalog if source["configuration_group"] == "data_source"]

        self.assertEqual(qianfan["configuration_group"], "llm")
        self.assertEqual(len(data_sources), len(DATA_SOURCE_CATALOG) - 1)

    def test_provider_enablement_api_persists_and_is_returned_in_source_status(self) -> None:
        disabled = self.client.put("/v1/web/sources/eastmoney/enabled", json={"enabled": False})

        self.assertEqual(disabled.status_code, 200)
        self.assertFalse(disabled.json()["source"]["enabled"])
        listed = self.client.get("/v1/web/sources").json()["sources"]
        eastmoney = next(source for source in listed if source["name"] == "eastmoney")
        self.assertFalse(eastmoney["enabled"])
        self.assertEqual(eastmoney["connectivity"]["status"], "disabled")
        self.assertFalse(ProviderActivationStore(self.provider_activation_path).is_enabled("eastmoney"))

        enabled = self.client.put("/v1/web/sources/eastmoney/enabled", json={"enabled": True})

        self.assertEqual(enabled.status_code, 200)
        self.assertTrue(enabled.json()["source"]["enabled"])

    def test_disabled_provider_connectivity_does_not_call_its_probe(self) -> None:
        calls: list[str | None] = []
        self.source_connectivity._probes["eastmoney"] = calls.append
        self.client.put("/v1/web/sources/eastmoney/enabled", json={"enabled": False})

        response = self.client.post("/v1/web/sources/eastmoney/connectivity")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["source"]["status"], "disabled")
        self.assertEqual(calls, [])

    def test_provider_enablement_api_rejects_non_boolean_values(self) -> None:
        response = self.client.put("/v1/web/sources/eastmoney/enabled", json={"enabled": "false"})

        self.assertEqual(response.status_code, 422)

    def test_connectivity_batch_can_target_only_the_llm_module(self) -> None:
        response = self.client.post("/v1/web/sources/connectivity?configuration_group=llm")

        self.assertEqual(response.status_code, 200)
        self.assertEqual([source["name"] for source in response.json()["sources"]], ["qianfan"])

    def test_source_connectivity_endpoint_returns_safe_remote_failure_state(self) -> None:
        response = self.client.post("/v1/web/sources/eastmoney/connectivity")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["source"]["status"], "remote_failure")
        self.assertNotIn("private upstream failure detail", response.text)
        listed = self.client.get("/v1/web/sources").json()["sources"]
        eastmoney = next(source for source in listed if source["name"] == "eastmoney")
        self.assertEqual(eastmoney["connectivity"]["status"], "remote_failure")

    def test_source_settings_assets_include_explicit_connectivity_controls_and_red_failure_style(self) -> None:
        page = self.client.get("/web/sources.html")
        script = self.client.get("/web/sources.js")
        styles = self.client.get("/web/styles.css")

        self.assertIn('id="test-all-sources"', page.text)
        self.assertIn('id="llm-settings-list"', page.text)
        self.assertIn('id="test-all-llms"', page.text)
        self.assertIn("LLM 模块", page.text)
        self.assertIn("测试连通", script.text)
        self.assertIn("configuration_group", script.text)
        self.assertIn('role", "switch"', script.text)
        self.assertIn("/enabled", script.text)
        self.assertIn("connectivity-remote_failure", styles.text)
        self.assertIn("provider-disabled", styles.text)

    def test_research_workspace_assets_include_professional_mode_controls(self) -> None:
        page = self.client.get("/web/")
        script = self.client.get("/web/app.js")
        form_script = self.client.get("/web/research-form.js")
        renderer_script = self.client.get("/web/result-renderer.js")
        styles = self.client.get("/web/styles.css")

        self.assertIn('id="professional-start-date"', page.text)
        self.assertIn('id="professional-market-options"', page.text)
        self.assertIn('id="professional-index-options"', page.text)
        self.assertIn('id="professional-metric-options"', page.text)
        self.assertIn("/v1/web/professional-research", script.text)
        self.assertIn("renderProfessionalIndexComparison", script.text)
        self.assertIn("outside-market", form_script.text)
        self.assertIn("export function renderProfessionalIndexComparison", renderer_script.text)
        self.assertIn("professional-comparison-grid", styles.text)

    def test_source_credentials_are_rejected_from_remote_clients_even_with_web_token(self) -> None:
        remote_client = TestClient(self.app, client=("203.0.113.10", 50_000))
        with patch.dict(os.environ, {"AGENT_WEB_ACCESS_TOKEN": "test-web-token"}, clear=False):
            response = remote_client.get("/v1/web/sources", headers={"X-Finance-Agent-Token": "test-web-token"})

        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
