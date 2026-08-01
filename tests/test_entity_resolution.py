from __future__ import annotations

import unittest

from ai_agent.application.entity_resolution import HSBC_ADR, HSBC_HK, KWEICHOW_MOUTAI, SecurityEntityResolver


class SecurityEntityResolverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.resolver = SecurityEntityResolver()

    def test_hsbc_chinese_name_keeps_hk_and_adr_candidates_visible(self) -> None:
        resolution = self.resolver.resolve("汇丰银行")

        self.assertTrue(resolution.is_ambiguous)
        self.assertEqual(resolution.candidates, (HSBC_HK, HSBC_ADR))

    def test_explicit_hk_code_resolves_to_hk_listing(self) -> None:
        resolution = self.resolver.resolve("查看 0005.HK 的基础概览")

        self.assertTrue(resolution.is_unique)
        self.assertEqual(resolution.candidates, (HSBC_HK,))

    def test_explicit_us_ticker_resolves_to_adr_listing(self) -> None:
        resolution = self.resolver.resolve("HSBC")

        self.assertTrue(resolution.is_unique)
        self.assertEqual(resolution.candidates, (HSBC_ADR,))

    def test_unknown_name_does_not_produce_a_guess(self) -> None:
        self.assertFalse(self.resolver.resolve("一家不存在的公司").candidates)

    def test_moutai_chinese_name_resolves_to_a_share_listing(self) -> None:
        resolution = self.resolver.resolve("贵州茅台")

        self.assertTrue(resolution.is_unique)
        self.assertEqual(resolution.candidates, (KWEICHOW_MOUTAI,))


if __name__ == "__main__":
    unittest.main()
