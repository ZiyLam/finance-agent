from __future__ import annotations

import json
import unittest

from ai_agent.application.security_discovery import SecurityDiscoveryService
from ai_agent.tools import FunctionTool, ToolRegistry


class SecurityDiscoveryTests(unittest.TestCase):
    def test_a_share_code_is_extracted_from_natural_language_before_search(self) -> None:
        received: list[object] = []

        def search(arguments: object) -> str:
            received.append(arguments)
            return json.dumps(
                {"matches": [{"code": "600000", "name": "浦发银行", "exchange": "SH"}]},
                ensure_ascii=False,
            )

        service = SecurityDiscoveryService(
            lambda: ToolRegistry((FunctionTool("eastmoney_security_search", "test", search),))
        )

        resolution = service.discover("查询 600000 最新价格")

        self.assertTrue(resolution.is_unique)
        self.assertEqual(resolution.candidates[0].display_symbol, "600000")
        self.assertEqual(received, [{"query": "600000", "limit": 5}])


if __name__ == "__main__":
    unittest.main()
