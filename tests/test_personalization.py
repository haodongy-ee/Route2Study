"""Tests for profile, directions, and calendar helpers."""

import unittest
from datetime import datetime, timezone

from personalization import (
    build_calendar_ics,
    build_google_maps_directions_url,
    build_plan_summary,
    normalize_profile,
    walking_speed_for_pace,
)


class PersonalizationTests(unittest.TestCase):
    def test_normalize_profile_filters_stale_locations(self) -> None:
        profile = {
            "display_name": "  Haodong  ",
            "default_start": "Missing dorm",
            "default_destination": "Missing class",
            "walking_pace": "Teleport",
            "minimum_study_minutes": 200,
            "transition_buffer_minutes": -5,
            "favorite_spaces": ["Van Pelt", "Missing", "Van Pelt"],
        }
        normalized = normalize_profile(
            profile,
            valid_starts=["Rodin"],
            valid_destinations=["Moore"],
            valid_study_spaces=["Van Pelt"],
        )
        self.assertEqual(normalized["display_name"], "Haodong")
        self.assertEqual(normalized["default_start"], "Rodin")
        self.assertEqual(normalized["default_destination"], "Moore")
        self.assertEqual(normalized["walking_pace"], "Standard")
        self.assertEqual(normalized["minimum_study_minutes"], 90)
        self.assertEqual(normalized["transition_buffer_minutes"], 0)
        self.assertEqual(normalized["favorite_spaces"], ["Van Pelt"])

    def test_walking_pace_changes_speed(self) -> None:
        self.assertLess(
            walking_speed_for_pace("Relaxed"),
            walking_speed_for_pace("Fast"),
        )
        self.assertEqual(walking_speed_for_pace("Unknown"), 80)

    def test_google_maps_url_contains_three_locations(self) -> None:
        url = build_google_maps_directions_url(
            {"latitude": 1, "longitude": 2},
            {"latitude": 3, "longitude": 4},
            {"latitude": 5, "longitude": 6},
        )
        self.assertIn("origin=1%2C2", url)
        self.assertIn("waypoints=3%2C4", url)
        self.assertIn("destination=5%2C6", url)
        self.assertIn("travelmode=walking", url)

    def test_plan_summary_and_calendar_are_portable(self) -> None:
        start = datetime(2026, 9, 23, 15, 0, tzinfo=timezone.utc)
        arrival = datetime(2026, 9, 23, 15, 10, tzinfo=timezone.utc)
        end = datetime(2026, 9, 23, 16, 30, tzinfo=timezone.utc)
        summary = build_plan_summary(
            start_label="Rodin",
            study_label="Van Pelt",
            destination_label="Moore",
            start_datetime=start,
            arrival_datetime=arrival,
            class_datetime=end,
            study_minutes=60,
            total_walking_minutes=20,
        )
        calendar = build_calendar_ics(
            start_datetime=arrival,
            end_datetime=end,
            study_label="Van Pelt",
            destination_label="Moore",
            description=summary,
            generated_at=start,
        )
        self.assertIn("Study: Van Pelt", summary)
        self.assertIn("BEGIN:VCALENDAR", calendar)
        self.assertIn("DTSTART:20260923T151000Z", calendar)
        self.assertIn("SUMMARY:Study at Van Pelt", calendar)
        self.assertTrue(calendar.endswith("\r\n"))


if __name__ == "__main__":
    unittest.main()
