from __future__ import annotations

import unittest

from ai_agent.langchain.retrieval import FinanceLanguageChain


class FinanceLanguageChainTests(unittest.TestCase):
    def test_lcel_rag_chain_returns_bounded_application_owned_context(self) -> None:
        context = FinanceLanguageChain(max_documents=3).invoke(
            "请分析 600000 在 2026-01-01 至 2026-03-31 的历史走势"
        )

        self.assertEqual(len(context.documents), 3)
        self.assertIn("研究", context.prompt_block())
        presentation = context.to_dict()
        self.assertEqual(presentation["framework"], "lcel_rag")
        self.assertEqual(presentation["document_count"], 3)
        self.assertEqual(presentation["intent"]["name"], "historical_research")

    def test_lcel_rag_chain_keeps_open_ended_requests_valid(self) -> None:
        context = FinanceLanguageChain().invoke("我最近有点担心市场，不知道该从哪里开始看")

        self.assertEqual(context.intent.name, "open_ended_research")
        self.assertTrue(context.documents)

    def test_open_ended_sector_prompt_defaults_to_beginner_strategy(self) -> None:
        context = FinanceLanguageChain().invoke("近期值得关注的板块")

        self.assertEqual(context.intent.name, "market_scan")
        self.assertEqual(context.intent.user_role, "个人研究者")
        self.assertIn("不超过三个", context.intent.strategy)

    def test_professional_terms_select_an_advanced_strategy(self) -> None:
        context = FinanceLanguageChain().invoke("请从 ROE、自由现金流和因子拥挤度分析近期板块")

        self.assertEqual(context.intent.user_role, "进阶研究者")
        self.assertIn("估值/盈利/拥挤度", context.intent.strategy)

    def test_lcel_rag_chain_rejects_blank_queries(self) -> None:
        with self.assertRaises(ValueError):
            FinanceLanguageChain().invoke("   ")


if __name__ == "__main__":
    unittest.main()
