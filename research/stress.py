"""Deterministic venue-disruption models for Penn stress experiments."""

from __future__ import annotations

from dataclasses import dataclass
import random


CROWD_MULTIPLIERS = {
    "Low": 1.0,
    "Medium": 0.75,
    "High": 0.5,
}


@dataclass(frozen=True)
class StressProfile:
    """One reproducible closure/crowding environment."""

    name: str
    closure_probability: float
    crowd_probabilities: tuple[float, float, float]

    def __post_init__(self) -> None:
        if not 0 <= self.closure_probability <= 1:
            raise ValueError("closure_probability must be between 0 and 1")
        if len(self.crowd_probabilities) != len(CROWD_MULTIPLIERS):
            raise ValueError("crowd_probabilities must contain Low, Medium, High")
        if any(value < 0 for value in self.crowd_probabilities):
            raise ValueError("crowd probabilities cannot be negative")
        if abs(sum(self.crowd_probabilities) - 1.0) > 1e-9:
            raise ValueError("crowd probabilities must sum to 1")


STRESS_PROFILES = {
    "baseline": StressProfile("baseline", 0.0, (1.0, 0.0, 0.0)),
    "moderate": StressProfile("moderate", 0.15, (0.50, 0.35, 0.15)),
    "severe": StressProfile("severe", 0.30, (0.20, 0.40, 0.40)),
}


def simulate_venue_conditions(
    venue_names: list[str],
    profile: StressProfile,
    uncertainty_seed: int,
    scenario_key: str,
) -> dict[str, dict[str, object]]:
    """Return repeatable closure and crowd states for every study venue.

    The scenario key is included in the random seed so the same uncertainty
    seed still produces different, but reproducible, conditions for each OD,
    preference, and time-budget combination.
    """

    rng = random.Random(
        f"route2study-v1|{uncertainty_seed}|{profile.name}|{scenario_key}"
    )
    crowd_levels = list(CROWD_MULTIPLIERS)
    conditions: dict[str, dict[str, object]] = {}
    for venue_name in venue_names:
        closed = rng.random() < profile.closure_probability
        crowd_level = rng.choices(
            crowd_levels,
            weights=profile.crowd_probabilities,
            k=1,
        )[0]
        conditions[venue_name] = {
            "closed": closed,
            "crowd_level": crowd_level,
            "prize_multiplier": 0.0 if closed else CROWD_MULTIPLIERS[crowd_level],
        }
    return conditions


def condition_summary(
    conditions: dict[str, dict[str, object]],
) -> dict[str, object]:
    """Create compact CSV-ready diagnostics for one simulated environment."""

    closed = sorted(
        name for name, status in conditions.items() if bool(status["closed"])
    )
    open_statuses = [
        status for status in conditions.values() if not bool(status["closed"])
    ]
    high_count = sum(
        status["crowd_level"] == "High" for status in open_statuses
    )
    medium_count = sum(
        status["crowd_level"] == "Medium" for status in open_statuses
    )
    mean_multiplier = (
        sum(float(status["prize_multiplier"]) for status in open_statuses)
        / len(open_statuses)
        if open_statuses
        else 0.0
    )
    return {
        "closed_venue_count": len(closed),
        "open_venue_count": len(open_statuses),
        "medium_crowding_count": medium_count,
        "high_crowding_count": high_count,
        "mean_crowd_multiplier": round(mean_multiplier, 4),
        "closed_venues": " | ".join(closed),
    }
