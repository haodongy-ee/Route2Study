"""Tests for operational metrics written by the Penn benchmark."""

import unittest

from research.orienteering import Solution
from research.run_penn_experiments import operational_metrics


class PennExperimentMetricTests(unittest.TestCase):
    def test_study_plan_slack_and_detour(self) -> None:
        solution = Solution(
            solver="test",
            route=(0, 1, 2),
            reward=5,
            travel_minutes=18,
            service_minutes=20,
            total_minutes=38,
            feasible=True,
        )
        metrics = operational_metrics(
            solution, time_budget=45, direct_travel_minutes=12
        )
        self.assertTrue(metrics["study_plan"])
        self.assertEqual(metrics["deadline_slack_minutes"], 7)
        self.assertEqual(metrics["walking_detour_minutes"], 6)
        self.assertEqual(metrics["walking_detour_percent"], 50)

    def test_direct_route_is_not_a_study_plan(self) -> None:
        solution = Solution(
            solver="test",
            route=(0, 1),
            reward=0,
            travel_minutes=12,
            service_minutes=0,
            total_minutes=12,
            feasible=True,
        )
        metrics = operational_metrics(
            solution, time_budget=45, direct_travel_minutes=12
        )
        self.assertFalse(metrics["study_plan"])
        self.assertEqual(metrics["walking_detour_minutes"], 0)


if __name__ == "__main__":
    unittest.main()
