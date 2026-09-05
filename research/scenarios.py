"""Deterministic synthetic instances for Route2Study baseline experiments."""

from __future__ import annotations

import math
import random

from research.orienteering import OrienteeringInstance


def generate_synthetic_instance(
    candidate_count: int,
    seed: int,
    time_budget: float = 90.0,
) -> OrienteeringInstance:
    """Generate one reproducible, campus-scale routing instance.

    Coordinates are normalized. Travel time is proportional to Euclidean
    distance and prizes combine a personal-preference score with a small amount
    of seeded variation. This is a controlled benchmark, not a claim about real
    Penn travel demand.
    """

    if candidate_count < 1:
        raise ValueError("candidate_count must be at least 1")

    rng = random.Random(seed)
    start = (0.0, 0.0)
    destination = (1.0, 0.0)
    candidates = [
        (rng.uniform(0.02, 0.98), rng.uniform(-0.55, 0.55))
        for _ in range(candidate_count)
    ]
    coordinates = [start, *candidates, destination]

    # About 32 walking minutes across the normalized east-west study area.
    minutes_per_coordinate_unit = 32.0
    travel_minutes = []
    for first in coordinates:
        row = []
        for second in coordinates:
            distance = math.dist(first, second)
            row.append(round(distance * minutes_per_coordinate_unit, 4))
        travel_minutes.append(tuple(row))

    preference_scores = [rng.uniform(1.0, 5.0) for _ in candidates]
    reliability_scores = [rng.uniform(0.65, 1.0) for _ in candidates]
    prizes = tuple(
        round(2.0 * preference * reliability, 4)
        for preference, reliability in zip(
            preference_scores,
            reliability_scores,
        )
    )
    service_minutes = tuple(
        float(rng.choice((8, 10, 12, 15, 18)))
        for _ in candidates
    )

    return OrienteeringInstance(
        travel_minutes=tuple(travel_minutes),
        prizes=prizes,
        service_minutes=service_minutes,
        time_budget=float(time_budget),
        name=f"synthetic_n{candidate_count}_seed{seed}",
    )
