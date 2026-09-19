"""Tests for experiment-result validation and aggregation."""

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from research.reporting import (
    load_saved_summary,
    summarize_results,
    summarize_results_with_uncertainty,
)


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
        self.results["visited_count"] = [1, 1, 0, 1]
        self.results["time_budget"] = [20, 30, 20, 30]
        self.results["total_minutes"] = [18, 25, 15, 28]
        self.results["travel_minutes"] = [10, 12, 9, 13]
        self.results["direct_travel_minutes"] = [8, 10, 9, 10]

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
        self.assertEqual(nearest["study_plan_rate_percent"], 50)
        self.assertEqual(nearest["mean_deadline_slack_minutes"], 3.5)
        self.assertEqual(nearest["mean_walking_detour_minutes"], 1.5)

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

    def test_rigorous_summary_is_reproducible(self) -> None:
        first = summarize_results_with_uncertainty(
            self.results, bootstrap_samples=200, seed=2026
        )
        second = summarize_results_with_uncertainty(
            self.results, bootstrap_samples=200, seed=2026
        )
        self.assertTrue(first.equals(second))
        nearest = first.loc[first["solver"] == "nearest"].iloc[0]
        self.assertAlmostEqual(nearest["reward_std"], 50 ** 0.5)
        self.assertEqual(nearest["median_runtime_ms"], 1)
        self.assertLessEqual(nearest["reward_ci_low"], nearest["mean_reward"])
        self.assertGreaterEqual(nearest["reward_ci_high"], nearest["mean_reward"])
        self.assertEqual(nearest["study_plan_rate_percent"], 50)
        self.assertEqual(nearest["mean_deadline_slack_minutes"], 3.5)

    def test_older_results_leave_detour_unknown(self) -> None:
        old = self.results.drop(columns="direct_travel_minutes")
        summary = summarize_results_with_uncertainty(
            old, bootstrap_samples=200
        )
        self.assertTrue(summary["mean_walking_detour_minutes"].isna().all())


if __name__ == "__main__":
    unittest.main()
