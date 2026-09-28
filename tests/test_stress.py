"""Tests for reproducible venue closure and crowding scenarios."""

import unittest

from research.stress import (
    STRESS_PROFILES,
    condition_summary,
    simulate_venue_conditions,
)


class StressScenarioTests(unittest.TestCase):
    def test_same_seed_and_scenario_are_reproducible(self) -> None:
        venues = ["Van Pelt", "Fisher", "Holman", "Houston"]
        first = simulate_venue_conditions(
            venues, STRESS_PROFILES["severe"], 2026, "Rodin|Moore|Quiet|20"
        )
        second = simulate_venue_conditions(
            venues, STRESS_PROFILES["severe"], 2026, "Rodin|Moore|Quiet|20"
        )
        self.assertEqual(first, second)

    def test_baseline_has_no_closures_or_crowding_penalty(self) -> None:
        conditions = simulate_venue_conditions(
            ["Van Pelt", "Fisher"],
            STRESS_PROFILES["baseline"],
            2026,
            "scenario",
        )
        summary = condition_summary(conditions)
        self.assertEqual(summary["closed_venue_count"], 0)
        self.assertEqual(summary["high_crowding_count"], 0)
        self.assertEqual(summary["mean_crowd_multiplier"], 1.0)

    def test_summary_counts_closed_and_crowded_venues(self) -> None:
        summary = condition_summary(
            {
                "A": {"closed": True, "crowd_level": "Low", "prize_multiplier": 0},
                "B": {"closed": False, "crowd_level": "Medium", "prize_multiplier": 0.75},
                "C": {"closed": False, "crowd_level": "High", "prize_multiplier": 0.5},
            }
        )
        self.assertEqual(summary["closed_venue_count"], 1)
        self.assertEqual(summary["open_venue_count"], 2)
        self.assertEqual(summary["medium_crowding_count"], 1)
        self.assertEqual(summary["high_crowding_count"], 1)
        self.assertEqual(summary["closed_venues"], "A")


if __name__ == "__main__":
    unittest.main()
