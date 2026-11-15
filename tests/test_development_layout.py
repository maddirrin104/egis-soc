"""W3 package paths preserve the historical hash-pinned import identities."""

import importlib
import unittest


MODULES = {
    "data": "development_data",
    "retrieval": "development_retrieval",
    "v1": "development_v1",
    "v2": "development_v2",
    "benchmark": "development_benchmark",
    "benchmark_run": "development_benchmark_run",
    "qa": "development_v2_qa",
}


class DevelopmentLayoutTests(unittest.TestCase):
    def test_old_and_grouped_module_paths_are_identical(self):
        for grouped, historical in MODULES.items():
            with self.subTest(grouped=grouped):
                old = importlib.import_module(f"egis_soc.{historical}")
                new = importlib.import_module(f"egis_soc.development.{grouped}")
                self.assertIs(old, new)

    def test_grouped_api_exports_qa_and_benchmark(self):
        from egis_soc import development
        self.assertIs(development.run_repeated_batch,
                      importlib.import_module("egis_soc.development.qa").run_repeated_batch)
        self.assertIs(development.run_fixture,
                      importlib.import_module("egis_soc.development.benchmark_run").run_fixture)


if __name__ == "__main__":
    unittest.main()
