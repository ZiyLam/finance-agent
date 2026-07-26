from __future__ import annotations

import unittest

from ai_agent.cli import run_source_command
from ai_agent.data_sources import DATA_SOURCE_CATALOG, DATA_SOURCES_BY_NAME, data_source_names


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
                "qianfan",
                "aktools",
                "baostock",
                "yfinance",
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


if __name__ == "__main__":
    unittest.main()
