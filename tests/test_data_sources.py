from __future__ import annotations

import unittest

from ai_agent.cli import run_source_command
from ai_agent.data_sources import (
    DATA_SOURCE_CATALOG,
    DATA_SOURCES_BY_NAME,
    SourceConfigurationGroup,
    configurations_in_group,
    data_source_names,
    ordered_data_sources,
)


class DataSourceCatalogTests(unittest.TestCase):
    def test_catalog_has_unique_maintenance_names_and_environment_variables(self) -> None:
        self.assertEqual(len(DATA_SOURCE_CATALOG), len(DATA_SOURCES_BY_NAME))
        self.assertEqual(
            len(DATA_SOURCE_CATALOG),
            len({definition.token_environment_variable for definition in DATA_SOURCE_CATALOG}),
        )
        self.assertEqual(
            set(data_source_names()),
            {
                "alltick",
                "alphavantage",
                "biying",
                "eodhd",
                "eastmoney",
                "qianfan",
                "bailian",
                "aktools",
                "baostock",
                "tickflow",
                "yfinance",
                "zhitu",
            },
        )

    def test_source_list_is_generated_from_the_catalog(self) -> None:
        output: list[str] = []

        result = run_source_command(["list"], output=output.append)

        self.assertEqual(result, 0)
        self.assertEqual(len(output), len(DATA_SOURCE_CATALOG))
        self.assertTrue(any(line.startswith("alltick:") for line in output))
        self.assertTrue(any(line.startswith("yfinance:") for line in output))
        self.assertTrue(all("credential slot" in line for line in output))
        self.assertTrue(all("tags [" in line for line in output))

    def test_source_status_views_are_ordered_by_priority_then_latency(self) -> None:
        ordered = ordered_data_sources()
        sort_keys = [(source.routing_priority, source.latency_rank, source.name) for source in ordered]

        self.assertEqual(sort_keys, sorted(sort_keys))
        self.assertEqual(data_source_names(), tuple(source.name for source in ordered))

    def test_llm_providers_are_owned_by_a_separate_settings_group(self) -> None:
        llms = configurations_in_group(SourceConfigurationGroup.LLM)
        market_data = configurations_in_group(SourceConfigurationGroup.DATA_SOURCE)

        self.assertEqual([definition.name for definition in llms], ["qianfan", "bailian"])
        self.assertNotIn("qianfan", {definition.name for definition in market_data})
        self.assertNotIn("bailian", {definition.name for definition in market_data})
        self.assertEqual(len(market_data), len(DATA_SOURCE_CATALOG) - 2)


if __name__ == "__main__":
    unittest.main()
