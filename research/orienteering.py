"""Baseline solvers for time-budgeted Route2Study experiments.

The research version of Route2Study is modeled as an open orienteering
problem. A route starts at node 0, may visit any subset of candidate nodes,
and must finish at the final node before the time budget expires.

Candidate nodes can represent study spaces or useful campus stops. Each one
has a personalized prize and a service duration. Travel times can later come
from the Penn pedestrian network; synthetic experiments use a generated
travel-time matrix.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import inf
from typing import Callable


EPSILON = 1e-9


@dataclass(frozen=True)
class OrienteeringInstance:
    """One time-budgeted routing problem.

    Node numbering is:
      - 0: starting location
      - 1..n: candidate stops
      - n + 1: destination class
    """

    travel_minutes: tuple[tuple[float, ...], ...]
    prizes: tuple[float, ...]
    service_minutes: tuple[float, ...]
    time_budget: float
    name: str = "instance"

    def __post_init__(self) -> None:
        node_count = len(self.prizes) + 2

        if len(self.travel_minutes) != node_count:
            raise ValueError("Travel matrix must contain n + 2 rows.")
        if any(len(row) != node_count for row in self.travel_minutes):
            raise ValueError("Travel matrix must be square.")
        if len(self.prizes) != len(self.service_minutes):
            raise ValueError("Prizes and service times must have equal length.")
        if self.time_budget <= 0:
            raise ValueError("Time budget must be positive.")
        if any(prize < 0 for prize in self.prizes):
            raise ValueError("Prizes cannot be negative.")
        if any(duration < 0 for duration in self.service_minutes):
            raise ValueError("Service times cannot be negative.")

    @property
    def candidate_count(self) -> int:
        return len(self.prizes)

    @property
    def destination(self) -> int:
        return self.candidate_count + 1


@dataclass(frozen=True)
class Solution:
    solver: str
    route: tuple[int, ...]
    reward: float
    travel_minutes: float
    service_minutes: float
    total_minutes: float
    feasible: bool

    @property
    def visited_count(self) -> int:
        return max(0, len(self.route) - 2)


def evaluate_route(
    instance: OrienteeringInstance,
    route: tuple[int, ...] | list[int],
    solver: str,
) -> Solution:
    """Calculate reward and time for a proposed route."""

    route = tuple(route)
    if len(route) < 2:
        raise ValueError("A route must contain a start and destination.")
    if route[0] != 0 or route[-1] != instance.destination:
        raise ValueError("Route must start at 0 and end at the destination.")

    candidate_nodes = route[1:-1]
    if len(candidate_nodes) != len(set(candidate_nodes)):
        raise ValueError("A candidate node cannot be visited twice.")
    if any(node < 1 or node > instance.candidate_count for node in candidate_nodes):
        raise ValueError("Route contains an invalid candidate node.")

    travel = sum(
        instance.travel_minutes[first][second]
        for first, second in zip(route, route[1:])
    )
    service = sum(instance.service_minutes[node - 1] for node in candidate_nodes)
    reward = sum(instance.prizes[node - 1] for node in candidate_nodes)
    total = travel + service

    return Solution(
        solver=solver,
        route=route,
        reward=round(reward, 6),
        travel_minutes=round(travel, 6),
        service_minutes=round(service, 6),
        total_minutes=round(total, 6),
        feasible=total <= instance.time_budget + EPSILON,
    )


def _construct_incremental_route(
    instance: OrienteeringInstance,
    solver_name: str,
    rank_key: Callable[[int, int], tuple[float, ...]],
) -> Solution:
    route = [0]
    current = 0
    elapsed = 0.0
    unvisited = set(range(1, instance.candidate_count + 1))

    while unvisited:
        feasible_candidates = []

        for node in unvisited:
            arrival = (
                elapsed
                + instance.travel_minutes[current][node]
                + instance.service_minutes[node - 1]
            )
            finish = arrival + instance.travel_minutes[node][instance.destination]

            if finish <= instance.time_budget + EPSILON:
                feasible_candidates.append(node)

        if not feasible_candidates:
            break

        selected = min(
            feasible_candidates,
            key=lambda node: rank_key(current, node),
        )
        elapsed += (
            instance.travel_minutes[current][selected]
            + instance.service_minutes[selected - 1]
        )
        route.append(selected)
        unvisited.remove(selected)
        current = selected

    route.append(instance.destination)
    return evaluate_route(instance, route, solver_name)


def solve_nearest(instance: OrienteeringInstance) -> Solution:
    """Visit the nearest feasible candidate until time runs out."""

    return _construct_incremental_route(
        instance,
        solver_name="nearest",
        rank_key=lambda current, node: (
            instance.travel_minutes[current][node],
            -instance.prizes[node - 1],
            node,
        ),
    )


def solve_greedy(instance: OrienteeringInstance) -> Solution:
    """Choose the best personalized-prize gain per added minute."""

    def rank_key(current: int, node: int) -> tuple[float, ...]:
        direct_to_destination = instance.travel_minutes[current][instance.destination]
        detour = (
            instance.travel_minutes[current][node]
            + instance.service_minutes[node - 1]
            + instance.travel_minutes[node][instance.destination]
            - direct_to_destination
        )
        ratio = instance.prizes[node - 1] / max(detour, EPSILON)
        return (-ratio, -instance.prizes[node - 1], node)

    return _construct_incremental_route(
        instance,
        solver_name="greedy_reward_per_minute",
        rank_key=rank_key,
    )


def solve_exact_dynamic_programming(instance: OrienteeringInstance) -> Solution:
    """Find an exact optimum for a small instance using subset dynamic programming.

    Runtime and memory grow exponentially, so this reference solver is intended
    for small benchmark instances. It supplies ground truth for measuring the
    optimality gap of faster heuristics and future learned policies.
    """

    destination = instance.destination
    direct_solution = evaluate_route(
        instance,
        (0, destination),
        solver="exact_dynamic_programming",
    )

    if not direct_solution.feasible:
        return direct_solution

    # state[(mask, last)] stores the minimum time used to reach `last`,
    # including the service time at every visited candidate.
    state: dict[tuple[int, int], float] = {}
    parent: dict[tuple[int, int], tuple[int, int] | None] = {}

    best_reward = 0.0
    best_total = direct_solution.total_minutes
    best_state: tuple[int, int] | None = None

    for candidate_index in range(instance.candidate_count):
        node = candidate_index + 1
        mask = 1 << candidate_index
        elapsed = (
            instance.travel_minutes[0][node]
            + instance.service_minutes[candidate_index]
        )

        if elapsed + instance.travel_minutes[node][destination] <= (
            instance.time_budget + EPSILON
        ):
            state[(mask, candidate_index)] = elapsed
            parent[(mask, candidate_index)] = None

    for mask in range(1, 1 << instance.candidate_count):
        mask_reward = sum(
            instance.prizes[index]
            for index in range(instance.candidate_count)
            if mask & (1 << index)
        )

        for last_index in range(instance.candidate_count):
            key = (mask, last_index)
            elapsed = state.get(key)
            if elapsed is None:
                continue

            last_node = last_index + 1
            total = elapsed + instance.travel_minutes[last_node][destination]

            if (
                mask_reward > best_reward + EPSILON
                or (
                    abs(mask_reward - best_reward) <= EPSILON
                    and total < best_total
                )
            ):
                best_reward = mask_reward
                best_total = total
                best_state = key

            for next_index in range(instance.candidate_count):
                next_bit = 1 << next_index
                if mask & next_bit:
                    continue

                next_node = next_index + 1
                next_elapsed = (
                    elapsed
                    + instance.travel_minutes[last_node][next_node]
                    + instance.service_minutes[next_index]
                )

                if next_elapsed + instance.travel_minutes[next_node][destination] > (
                    instance.time_budget + EPSILON
                ):
                    continue

                next_mask = mask | next_bit
                next_key = (next_mask, next_index)
                if next_elapsed + EPSILON < state.get(next_key, inf):
                    state[next_key] = next_elapsed
                    parent[next_key] = key

    if best_state is None:
        return direct_solution

    reversed_candidates = []
    cursor: tuple[int, int] | None = best_state
    while cursor is not None:
        _, last_index = cursor
        reversed_candidates.append(last_index + 1)
        cursor = parent[cursor]

    route = (0, *reversed(reversed_candidates), destination)
    return evaluate_route(instance, route, "exact_dynamic_programming")
