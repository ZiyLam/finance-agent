from __future__ import annotations

import unittest

from ai_agent.tools import ToolRegistry, create_echo_tool


class ToolRegistryTests(unittest.TestCase):
    def test_executes_registered_tool(self) -> None:
        registry = ToolRegistry((create_echo_tool(),))
        self.assertEqual(registry.execute("echo", {"text": "hello"}), "hello")

    def test_returns_safe_error_for_unknown_tool(self) -> None:
        registry = ToolRegistry()
        self.assertEqual(
            registry.execute("missing", {}),
            "ERROR: Tool 'missing' is not registered.",
        )


if __name__ == "__main__":
    unittest.main()
