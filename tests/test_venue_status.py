"""Tests for official-hours parsing and live crowd reports."""

import unittest
from datetime import date, datetime, timedelta

from venue_status import (
    CrowdReportStore,
    extract_calendar_hours,
    extract_library_hours,
    fall_2026_regular_hours,
    is_open_at,
)


class VenueStatusTests(unittest.TestCase):
    def test_extracts_supported_library_hours(self) -> None:
        page = """
        <ul>
          <li>Van Pelt-Dietrich Library Center <a>Hours</a>: 10am - 12am</li>
          <li>Fisher Fine Arts Library <a>Hours</a>: Closed</li>
          <li>Holman Biotech Commons <a>Hours</a>: 12pm - 8pm</li>
        </ul>
        """
        self.assertEqual(
            extract_library_hours(page),
            {
                "Van Pelt Library": "10am - 12am",
                "Fisher Fine Arts Library": "Closed",
                "Holman Biotech Commons": "12pm - 8pm",
            },
        )

    def test_open_status_handles_midnight_closing(self) -> None:
        self.assertTrue(is_open_at("10am - 12am", datetime(2026, 9, 14, 23, 30)))
        self.assertFalse(is_open_at("10am - 12am", datetime(2026, 9, 14, 9, 30)))
        self.assertFalse(is_open_at("Closed", datetime(2026, 9, 14, 12, 0)))
        self.assertTrue(is_open_at("24 hours", datetime(2026, 9, 14, 12, 0)))
        self.assertTrue(is_open_at("Closes 9pm", datetime(2026, 9, 14, 20, 0)))

    def test_extracts_exact_date_from_venue_calendar(self) -> None:
        page = """
        <ul>
          <li><div class="date">Sun, Oct 11, 2026</div>
              <div class="hours">12pm - 8pm</div></li>
          <li><div class="date">Mon, Oct 12, 2026</div>
              <div class="today">Today</div>
              <div class="hours">8am - 12am</div></li>
        </ul>
        """
        self.assertEqual(
            extract_calendar_hours(page, date(2026, 10, 12)),
            "8am - 12am",
        )
        self.assertIsNone(extract_calendar_hours(page, date(2026, 10, 13)))

    def test_fall_schedule_uses_correct_weekday(self) -> None:
        monday = fall_2026_regular_hours(datetime(2026, 10, 12, 12, 0))
        self.assertEqual(monday["Van Pelt Library"], "8:30am - 12am")
        self.assertEqual(monday["Fisher Fine Arts Library"], "9am - 12am")
        self.assertEqual(fall_2026_regular_hours(datetime(2026, 12, 8, 12, 0)), {})
        self.assertEqual(fall_2026_regular_hours(datetime(2026, 11, 27, 12, 0)), {})

    def test_crowd_reports_expire_and_aggregate(self) -> None:
        store = CrowdReportStore(retention_hours=2)
        now = datetime.now().astimezone()
        store.add("Library", "Quiet", now - timedelta(minutes=30))
        store.add("Library", "Busy", now - timedelta(minutes=10))
        summary = store.summarize("Library", now)
        self.assertEqual(summary.level, "Moderate")
        self.assertEqual(summary.reports, 2)
        expired = store.summarize("Library", now + timedelta(hours=3))
        self.assertEqual(expired.level, "Unknown")


if __name__ == "__main__":
    unittest.main()
