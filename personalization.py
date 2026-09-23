"""Pure helpers for Route2Study's session-level personalization features."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from urllib.parse import urlencode


WALKING_PACES = {
    "Relaxed": 65,
    "Standard": 80,
    "Fast": 95,
}

DEFAULT_PROFILE = {
    "display_name": "",
    "default_start": "Rodin College House",
    "default_destination": "Moore School Building",
    "study_preference": "Quiet",
    "walking_pace": "Standard",
    "minimum_study_minutes": 15,
    "transition_buffer_minutes": 10,
    "favorite_spaces": [],
    "crowd_aware": True,
    "require_verified_open": False,
}


def normalize_profile(
    profile=None,
    *,
    valid_starts=(),
    valid_destinations=(),
    valid_study_spaces=(),
):
    """Return a safe profile while preserving valid user-selected values."""

    normalized = DEFAULT_PROFILE.copy()
    normalized["favorite_spaces"] = []
    if isinstance(profile, dict):
        normalized.update(profile)

    starts = list(valid_starts)
    destinations = list(valid_destinations)
    study_spaces = set(valid_study_spaces)

    if starts and normalized["default_start"] not in starts:
        normalized["default_start"] = starts[0]
    if (
        destinations
        and normalized["default_destination"] not in destinations
    ):
        normalized["default_destination"] = destinations[0]
    if normalized["walking_pace"] not in WALKING_PACES:
        normalized["walking_pace"] = DEFAULT_PROFILE["walking_pace"]

    normalized["display_name"] = str(normalized["display_name"]).strip()[:40]
    normalized["minimum_study_minutes"] = max(
        10, min(90, int(normalized["minimum_study_minutes"]))
    )
    normalized["transition_buffer_minutes"] = max(
        0, min(30, int(normalized["transition_buffer_minutes"]))
    )
    normalized["favorite_spaces"] = [
        name
        for name in dict.fromkeys(normalized.get("favorite_spaces") or [])
        if name in study_spaces
    ][:5]
    normalized["crowd_aware"] = bool(normalized["crowd_aware"])
    normalized["require_verified_open"] = bool(
        normalized["require_verified_open"]
    )
    return normalized


def walking_speed_for_pace(pace):
    """Return walking speed in meters per minute for a named pace."""

    return WALKING_PACES.get(pace, WALKING_PACES["Standard"])


def build_google_maps_directions_url(origin, waypoint, destination):
    """Build a two-leg Google Maps walking-directions URL."""

    params = {
        "api": "1",
        "origin": f"{origin['latitude']},{origin['longitude']}",
        "destination": (
            f"{destination['latitude']},{destination['longitude']}"
        ),
        "waypoints": f"{waypoint['latitude']},{waypoint['longitude']}",
        "travelmode": "walking",
    }
    return "https://www.google.com/maps/dir/?" + urlencode(params)


def build_plan_summary(
    *,
    start_label,
    study_label,
    destination_label,
    start_datetime,
    arrival_datetime,
    class_datetime,
    study_minutes,
    total_walking_minutes,
):
    """Create a compact text summary suitable for download or sharing."""

    return "\n".join(
        [
            "Route2Study plan",
            f"Start: {start_label} at {start_datetime.strftime('%I:%M %p')}",
            (
                f"Study: {study_label} from about "
                f"{arrival_datetime.strftime('%I:%M %p')} "
                f"for {study_minutes} minutes"
            ),
            (
                f"Class: {destination_label} at "
                f"{class_datetime.strftime('%I:%M %p')}"
            ),
            f"Total walking: {total_walking_minutes} minutes",
        ]
    )


def _escape_ics(value):
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def build_calendar_ics(
    *,
    start_datetime,
    end_datetime,
    study_label,
    destination_label,
    description,
    generated_at=None,
):
    """Create a standards-friendly calendar event for the planned study block."""

    generated_at = generated_at or datetime.now(timezone.utc)

    def utc_stamp(value):
        return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    uid_seed = (
        f"{start_datetime.isoformat()}-{study_label}-{destination_label}"
    ).encode("utf-8")
    uid = sha256(uid_seed).hexdigest()[:24] + "@route2study"
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Route2Study//Campus Planner//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{utc_stamp(generated_at)}",
        f"DTSTART:{utc_stamp(start_datetime)}",
        f"DTEND:{utc_stamp(end_datetime)}",
        f"SUMMARY:{_escape_ics('Study at ' + study_label)}",
        f"LOCATION:{_escape_ics(study_label)}",
        f"DESCRIPTION:{_escape_ics(description)}",
        "END:VEVENT",
        "END:VCALENDAR",
        "",
    ]
    return "\r\n".join(lines)
