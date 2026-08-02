from __future__ import annotations

import unittest

from ai_agent.tools import FunctionTool, ToolRegistry, ToolSideEffect, create_echo_tool


class ToolRegistryTests(unittest.TestCase):
    def test_executes_registered_tool(self) -> None:
        registry = ToolRegistry((create_echo_tool(),))
        self.assertEqual(registry.execute("echo", {"text": "hello"}), "hello")
        self.assertEqual(registry.definitions()[0].side_effect, ToolSideEffect.READ_ONLY)

    def test_rejects_mutating_tool_before_it_can_reach_the_agent(self) -> None:
        calls: list[object] = []
        tool = FunctionTool(
            "place_order",
            "unsafe test tool",
            lambda arguments: calls.append(arguments) or "unexpected",
            side_effect=ToolSideEffect.MUTATING,
        )

        with self.assertRaisesRegex(ValueError, "read-only"):
            ToolRegistry((tool,))

        self.assertEqual(calls, [])

    def test_rejects_tool_without_a_side_effect_declaration(self) -> None:
        class UndeclaredTool:
            name = "undeclared"
            description = "missing capability metadata"

            def run(self, _arguments: object) -> str:
                return "unexpected"

        with self.assertRaisesRegex(ValueError, "side-effect capability"):
            ToolRegistry((UndeclaredTool(),))  # type: ignore[arg-type]

    def test_returns_safe_error_for_unknown_tool(self) -> None:
        registry = ToolRegistry()
        self.assertEqual(
            registry.execute("missing", {}),
            "ERROR: Tool 'missing' is not registered.",
        )

    def test_unexpected_tool_failure_is_sanitized_and_keeps_the_loop_recoverable(self) -> None:
        def failing_tool(_arguments: object) -> str:
            raise RuntimeError("upstream response included a secret")

        registry = ToolRegistry((FunctionTool("failing", "test failure", failing_tool),))

        response = registry.execute("failing", {})

        self.assertEqual(
            response,
            "ERROR: Tool 'failing' failed unexpectedly; retry later or use another available source.",
        )
        self.assertNotIn("secret", response)

    def test_disabled_provider_is_hidden_and_cannot_execute_a_known_tool(self) -> None:
        calls: list[object] = []
        tool = FunctionTool(
            "yfinance_market_data",
            "test provider gate",
            lambda arguments: calls.append(arguments) or "unexpected",
        )
        registry = ToolRegistry((tool,), provider_enabled=lambda source: source != "yfinance")

        self.assertEqual(registry.definitions(), ())
        self.assertEqual(
            registry.execute("yfinance_market_data", {"symbol": "AAPL"}),
            "ERROR: Provider for tool 'yfinance_market_data' is disabled in parameter settings.",
        )
        self.assertEqual(calls, [])

    def test_provider_policy_failure_fails_closed(self) -> None:
        tool = FunctionTool("eastmoney_market_scan", "test provider gate", lambda _arguments: "unexpected")

        def unreadable_policy(_source: str) -> bool:
            raise OSError("private local settings detail")

        registry = ToolRegistry((tool,), provider_enabled=unreadable_policy)

        self.assertEqual(registry.definitions(), ())
        self.assertIn("disabled", registry.execute("eastmoney_market_scan", {}))


if __name__ == "__main__":
    unittest.main()
