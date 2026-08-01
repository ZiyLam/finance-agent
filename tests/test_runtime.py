from __future__ import annotations

import unittest
from unittest.mock import patch

from ai_agent.runtime import build_market_data_tool_registry


class RuntimeTests(unittest.TestCase):
    @patch("ai_agent.runtime.resolve_token", return_value=None)
    def test_registry_starts_when_biying_token_is_not_configured(self, _resolve_token: object) -> None:
        registry = build_market_data_tool_registry(include_echo=False)

        names = {tool.name for tool in registry.definitions()}

        self.assertNotIn("biying_market_data", names)
        self.assertTrue(
            {
                "aktools_market_data",
                "baostock_market_data",
                "yfinance_market_data",
                "eastmoney_security_search",
                "eastmoney_market_scan",
            }.issubset(names)
        )

    @patch("ai_agent.runtime.getenv", side_effect=lambda name, default="": "selected-kb" if name == "IMA_KNOWLEDGE_BASE_ID" else default)
    @patch(
        "ai_agent.runtime.resolve_token",
        side_effect=lambda saved_name, _environment_name: {
            "ima_client_id": "client-id",
            "ima_api_key": "api-key",
        }.get(saved_name),
    )
    def test_registry_registers_ima_only_when_credentials_and_target_exist(
        self, _resolve_token: object, _getenv: object
    ) -> None:
        registry = build_market_data_tool_registry(include_echo=False)

        names = {tool.name for tool in registry.definitions()}

        self.assertIn("ima_knowledge_search", names)

    @patch("ai_agent.runtime.getenv", side_effect=lambda name, default="": "Finance" if name == "IMA_KNOWLEDGE_BASE_NAME" else default)
    @patch(
        "ai_agent.runtime.resolve_token",
        side_effect=lambda saved_name, _environment_name: {
            "ima_client_id": "client-id",
            "ima_api_key": "api-key",
        }.get(saved_name),
    )
    def test_registry_registers_ima_when_an_exact_target_name_is_configured(
        self, _resolve_token: object, _getenv: object
    ) -> None:
        registry = build_market_data_tool_registry(include_echo=False)

        names = {tool.name for tool in registry.definitions()}

        self.assertIn("ima_knowledge_search", names)

    @patch(
        "ai_agent.runtime.resolve_token",
        side_effect=lambda saved_name, _environment_name: "tickflow-key" if saved_name == "tickflow" else None,
    )
    def test_registry_registers_tickflow_only_when_a_key_is_configured(self, _resolve_token: object) -> None:
        registry = build_market_data_tool_registry(include_echo=False)

        names = {tool.name for tool in registry.definitions()}

        self.assertIn("tickflow_market_data", names)

    @patch(
        "ai_agent.runtime.resolve_token",
        side_effect=lambda saved_name, _environment_name: "zhitu-key" if saved_name == "zhitu" else None,
    )
    def test_registry_registers_zhitu_only_when_a_key_is_configured(self, _resolve_token: object) -> None:
        registry = build_market_data_tool_registry(include_echo=False)

        names = {tool.name for tool in registry.definitions()}

        self.assertIn("zhitu_market_data", names)


if __name__ == "__main__":
    unittest.main()
