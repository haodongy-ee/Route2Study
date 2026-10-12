"""Live venue-hours and anonymous crowd-report utilities for Route2Study."""

from __future__ import annotations

import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from html.parser import HTMLParser
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


PENN_LIBRARY_HOURS_URL = "https://www.library.upenn.edu/about/hours"
VENUE_TO_OFFICIAL_NAME = {
    "Van Pelt Library": "Van Pelt-Dietrich Library Center",
    "Fisher Fine Arts Library": "Fisher Fine Arts Library",
    "Holman Biotech Commons": "Holman Biotech Commons",
}
PENN_LIBRARY_CALENDAR_URLS = {
    "Van Pelt Library": "https://www.library.upenn.edu/vanpelt/hours",
    "Fisher Fine Arts Library": "https://www.library.upenn.edu/finearts/hours",
    "Holman Biotech Commons": "https://www.library.upenn.edu/holman/hours",
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
PENN_TIMEZONE = ZoneInfo("America/New_York")
HOURS_VALUE_PATTERN = (
    r"Closed|24\s+hours|Open\s+24\s+hours|"
    r"(?:Opens|Closes)\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)|"
    r"\d{1,2}(?::\d{2})?\s*(?:am|pm)\s*-\s*"
    r"\d{1,2}(?::\d{2})?\s*(?:am|pm)"
)


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
            rf"({HOURS_VALUE_PATTERN})",
            re.IGNORECASE,
        )
        match = pattern.search(text_content)
        if match:
            hours[venue_name] = " ".join(match.group(1).split())

    return hours


def extract_calendar_hours(page_html: str, target_date: date) -> str | None:
    """Extract one date from an individual Penn Libraries calendar page."""

    parser = _VisibleTextParser()
    parser.feed(page_html)
    text_content = " ".join(parser.parts)
    date_label = (
        f"{target_date.strftime('%a')}, {target_date.strftime('%b')} "
        f"{target_date.day}, {target_date.year}"
    )
    pattern = re.compile(
        rf"{re.escape(date_label)}\s+(?:Today\s+)?({HOURS_VALUE_PATTERN})",
        re.IGNORECASE,
    )
    match = pattern.search(text_content)
    return " ".join(match.group(1).split()) if match else None


def _fetch_html(url: str, timeout_seconds: int) -> str:
    request = Request(
        url,
        headers={"User-Agent": "Route2Study/2.1 (+https://route2study.streamlit.app/)"},
    )
    with urlopen(request, timeout=timeout_seconds) as response:
        return response.read().decode("utf-8", errors="replace")


def _calendar_url(base_url: str, target_date: date) -> str:
    query = urlencode(
        {
            "month": f"{target_date.month:02d}",
            "year": target_date.year,
            "day": target_date.day,
        }
    )
    return f"{base_url}?{query}"


def fetch_penn_library_hours(
    planning_moment: datetime | None = None,
    timeout_seconds: int = 8,
) -> dict[str, str]:
    """Fetch official hours with summary-page and calendar-page fallbacks.

    Penn's summary page is the fastest source for today. If it is unavailable,
    incomplete, or a different planning date is requested, the three venue
    calendar pages are queried concurrently and parsed for that exact date.
    """

    moment = planning_moment or datetime.now(PENN_TIMEZONE)
    if moment.tzinfo is not None:
        target_date = moment.astimezone(PENN_TIMEZONE).date()
    else:
        target_date = moment.date()
    penn_today = datetime.now(PENN_TIMEZONE).date()

    hours: dict[str, str] = {}
    errors: list[str] = []
    if target_date == penn_today:
        try:
            hours.update(
                extract_library_hours(
                    _fetch_html(PENN_LIBRARY_HOURS_URL, timeout_seconds)
                )
            )
        except (OSError, TimeoutError, ValueError) as error:
            errors.append(f"summary: {error}")

    missing = [venue for venue in VENUE_TO_OFFICIAL_NAME if venue not in hours]
    if missing:
        with ThreadPoolExecutor(max_workers=len(missing)) as executor:
            futures = {
                executor.submit(
                    _fetch_html,
                    _calendar_url(PENN_LIBRARY_CALENDAR_URLS[venue], target_date),
                    timeout_seconds,
                ): venue
                for venue in missing
            }
            for future in as_completed(futures):
                venue = futures[future]
                try:
                    value = extract_calendar_hours(future.result(), target_date)
                    if value:
                        hours[venue] = value
                    else:
                        errors.append(f"{venue}: date not found")
                except (OSError, TimeoutError, ValueError) as error:
                    errors.append(f"{venue}: {error}")

    if not hours:
        detail = "; ".join(errors) or "no supported locations returned"
        raise OSError(f"Penn Libraries hours unavailable ({detail})")
    return hours


def fall_2026_regular_hours(moment: datetime) -> dict[str, str]:
    """Regular fall-term pattern, verified against October 2026 calendars.

    This fallback deliberately excludes Thanksgiving break and dates after the
    last day of classes. Special-event exceptions still require the live feed,
    and the UI labels this data as a regular-week estimate.
    """

    target_date = moment.date()
    if not date(2026, 8, 25) <= target_date <= date(2026, 12, 7):
        return {}
    if date(2026, 11, 26) <= target_date <= date(2026, 11, 29):
        return {}
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
    if normalized in {"24 hours", "open 24 hours"}:
        return True
    if normalized.startswith("opens"):
        return moment.time() >= _parse_clock(normalized.removeprefix("opens"))
    if normalized.startswith("closes"):
        closing = _parse_clock(normalized.removeprefix("closes"))
        return closing == time(0, 0) or moment.time() < closing
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
