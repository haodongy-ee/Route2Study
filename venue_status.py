"""Live venue-hours and anonymous crowd-report utilities for Route2Study."""

from __future__ import annotations

import re
import threading
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from html.parser import HTMLParser
from urllib.request import Request, urlopen


PENN_LIBRARY_HOURS_URL = "https://www.library.upenn.edu/about/hours"
VENUE_TO_OFFICIAL_NAME = {
    "Van Pelt Library": "Van Pelt-Dietrich Library Center",
    "Fisher Fine Arts Library": "Fisher Fine Arts Library",
    "Holman Biotech Commons": "Holman Biotech Commons",
}
FALL_2026_REGULAR_HOURS = {
    "Van Pelt Library": (
        "10am - 12am",
        "8:30am - 12am",
        "8:30am - 12am",
        "8:30am - 12am",
        "8:30am - 12am",
        "8:30am - 9pm",
        "10am - 6pm",
    ),
    "Fisher Fine Arts Library": (
        "12pm - 12am",
        "9am - 12am",
        "9am - 12am",
        "9am - 12am",
        "9am - 12am",
        "9am - 6pm",
        "10am - 6pm",
    ),
    "Holman Biotech Commons": (
        "12pm - 8pm",
        "8am - 12am",
        "8am - 12am",
        "8am - 12am",
        "8am - 12am",
        "8am - 10pm",
        "12pm - 8pm",
    ),
}


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._hidden_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"script", "style", "noscript"}:
            self._hidden_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._hidden_depth:
            self._hidden_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._hidden_depth and data.strip():
            self.parts.append(data.strip())


def extract_library_hours(page_html: str) -> dict[str, str]:
    """Extract today's hours for Route2Study libraries from Penn's page."""

    parser = _VisibleTextParser()
    parser.feed(page_html)
    text_content = " ".join(parser.parts)
    hours: dict[str, str] = {}

    for venue_name, official_name in VENUE_TO_OFFICIAL_NAME.items():
        pattern = re.compile(
            rf"{re.escape(official_name)}\s+Hours\s*:\s*"
            r"(Closed|Opens\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)|"
            r"\d{1,2}(?::\d{2})?\s*(?:am|pm)\s*-\s*"
            r"\d{1,2}(?::\d{2})?\s*(?:am|pm))",
            re.IGNORECASE,
        )
        match = pattern.search(text_content)
        if match:
            hours[venue_name] = " ".join(match.group(1).split())

    return hours


def fetch_penn_library_hours(timeout_seconds: int = 8) -> dict[str, str]:
    """Fetch today's official Penn Libraries hours without extra packages."""

    request = Request(
        PENN_LIBRARY_HOURS_URL,
        headers={"User-Agent": "Route2Study/2.0 (+https://route2study.streamlit.app/)"},
    )
    with urlopen(request, timeout=timeout_seconds) as response:
        page_html = response.read().decode("utf-8", errors="replace")
    return extract_library_hours(page_html)


def fall_2026_regular_hours(moment: datetime) -> dict[str, str]:
    """Official regular fall schedule fallback, verified September 14, 2026.

    Holiday and special-event exceptions require the live Penn feed, so the UI
    identifies this as a fallback whenever the official page cannot be reached.
    """

    # datetime.weekday(): Monday=0; schedules above start with Sunday.
    schedule_index = (moment.weekday() + 1) % 7
    return {
        venue: weekly_hours[schedule_index]
        for venue, weekly_hours in FALL_2026_REGULAR_HOURS.items()
    }


def _parse_clock(value: str) -> time:
    normalized = value.strip().lower().replace(" ", "")
    for clock_format in ("%I:%M%p", "%I%p"):
        try:
            return datetime.strptime(normalized, clock_format).time()
        except ValueError:
            continue
    raise ValueError(f"Unsupported time: {value}")


def is_open_at(hours_text: str | None, moment: datetime) -> bool | None:
    """Return open/closed for a planned time, or None when not knowable."""

    if not hours_text:
        return None
    normalized = hours_text.strip().lower()
    if normalized == "closed":
        return False
    if normalized.startswith("opens"):
        return moment.time() >= _parse_clock(normalized.removeprefix("opens"))
    if "-" not in normalized:
        return None

    opening_text, closing_text = normalized.split("-", maxsplit=1)
    opening = _parse_clock(opening_text)
    closing = _parse_clock(closing_text)
    current = moment.time()
    if closing <= opening:
        return current >= opening or current < closing
    return opening <= current < closing


@dataclass(frozen=True)
class CrowdSummary:
    level: str
    reports: int
    latest_at: datetime | None


class CrowdReportStore:
    """Thread-safe, process-local anonymous live reports.

    Streamlit Community Cloud does not provide a durable database by default.
    Reports are intentionally anonymous and expire after two hours; they reset
    when the app process restarts.
    """

    LEVELS = ("Quiet", "Moderate", "Busy", "Full")

    def __init__(self, retention_hours: int = 2) -> None:
        self.retention = timedelta(hours=retention_hours)
        self._reports: dict[str, deque[tuple[datetime, str]]] = defaultdict(deque)
        self._lock = threading.Lock()

    def add(self, venue: str, level: str, reported_at: datetime | None = None) -> None:
        if level not in self.LEVELS:
            raise ValueError(f"Unsupported crowd level: {level}")
        timestamp = reported_at or datetime.now().astimezone()
        with self._lock:
            self._reports[venue].append((timestamp, level))
            self._prune(venue, timestamp)

    def summarize(self, venue: str, now: datetime | None = None) -> CrowdSummary:
        timestamp = now or datetime.now().astimezone()
        with self._lock:
            self._prune(venue, timestamp)
            reports = list(self._reports[venue])
        if not reports:
            return CrowdSummary("Unknown", 0, None)

        weights = {"Quiet": 0, "Moderate": 1, "Busy": 2, "Full": 3}
        average = sum(weights[level] for _, level in reports) / len(reports)
        aggregate = self.LEVELS[min(3, round(average))]
        return CrowdSummary(aggregate, len(reports), reports[-1][0])

    def _prune(self, venue: str, now: datetime) -> None:
        cutoff = now - self.retention
        reports = self._reports[venue]
        while reports and reports[0][0] < cutoff:
            reports.popleft()


def crowd_penalty(level: str) -> float:
    """Recommendation penalty for a verified recent crowd report."""

    return {"Unknown": 0.0, "Quiet": 0.0, "Moderate": 8.0, "Busy": 25.0, "Full": 1000.0}[level]
