"""Tests for experiment-result validation and aggregation."""

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from research.reporting import load_saved_summary, summarize_results


class ReportingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.results = pd.DataFrame(
            [
                {
                    "solver": "exact_dynamic_programming",
                    "reward": 10,
                    "optimality_gap_percent": 0,
                    "feasible": True,
                    "runtime_ms": 2,
                },
                {
                    "solver": "exact_dynamic_programming",
                    "reward": 20,
                    "optimality_gap_percent": 0,
                    "feasible": True,
                    "runtime_ms": 4,
                },
                {
                    "solver": "nearest",
                    "reward": 8,
                    "optimality_gap_percent": 20,
                    "feasible": "False",
                    "runtime_ms": 1,
                },
                {
                    "solver": "nearest",
                    "reward": 18,
                    "optimality_gap_percent": 10,
                    "feasible": "True",
                    "runtime_ms": 1,
                },
            ]
        )

    def test_summarize_results(self) -> None:
        summary = summarize_results(self.results)
        exact = summary.loc[
            summary["solver"] == "exact_dynamic_programming"
        ].iloc[0]
        nearest = summary.loc[summary["solver"] == "nearest"].iloc[0]

        self.assertEqual(exact["method"], "Exact dynamic programming")
        self.assertEqual(exact["scenarios"], 2)
        self.assertEqual(exact["mean_reward"], 15)
        self.assertEqual(nearest["mean_gap_percent"], 15)
        self.assertEqual(nearest["feasible_rate_percent"], 50)

    def test_missing_column_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "runtime_ms"):
            summarize_results(self.results.drop(columns="runtime_ms"))

    def test_saved_summary_loader_adds_method_label(self) -> None:
        saved = pd.DataFrame(
            [
                {
                    "solver": "greedy_reward_per_minute",
                    "scenarios": 12,
                    "mean_reward": 14.467,
                    "mean_gap_percent": 0,
                    "feasible_rate_percent": 100,
                    "mean_runtime_ms": 0.016,
                }
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "summary.csv"
            saved.to_csv(path, index=False)
            loaded = load_saved_summary(path)

        self.assertEqual(loaded.iloc[0]["method"], "Greedy reward/minute")


if __name__ == "__main__":
    unittest.main()
