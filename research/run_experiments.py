"""Run reproducible Route2Study baseline experiments.

From the project root:
    python research/run_experiments.py
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from research.orienteering import (  # noqa: E402
    Solution,
    solve_exact_dynamic_programming,
    solve_greedy,
    solve_nearest,
)
from research.scenarios import generate_synthetic_instance  # noqa: E402


SOLVERS = (
    solve_exact_dynamic_programming,
    solve_greedy,
    solve_nearest,
)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare Route2Study routing baselines.",
    )
    parser.add_argument(
        "--nodes",
        type=int,
        nargs="+",
        default=[6, 8, 10],
        help="Candidate counts. Keep these small for the exact solver.",
    )
    parser.add_argument(
        "--instances",
        type=int,
        default=10,
        help="Number of seeded instances for each candidate count.",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--time-budget", type=float, default=90.0)
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "research" / "results" / "baseline_results.csv",
    )
    return parser.parse_args()


def timed_solve(solver, instance) -> tuple[Solution, float]:
    started = time.perf_counter()
    solution = solver(instance)
    runtime_ms = (time.perf_counter() - started) * 1000
    return solution, runtime_ms


def solution_record(
    solution: Solution,
    runtime_ms: float,
    candidate_count: int,
    instance_index: int,
    instance_seed: int,
    time_budget: float,
    optimal_reward: float,
) -> dict[str, object]:
    if optimal_reward > 0:
        gap = 100.0 * (optimal_reward - solution.reward) / optimal_reward
    else:
        gap = 0.0

    return {
        "candidate_count": candidate_count,
        "instance_index": instance_index,
        "instance_seed": instance_seed,
        "solver": solution.solver,
        "reward": solution.reward,
        "optimal_reward": optimal_reward,
        "optimality_gap_percent": round(max(0.0, gap), 4),
        "travel_minutes": solution.travel_minutes,
        "service_minutes": solution.service_minutes,
        "total_minutes": solution.total_minutes,
        "time_budget": time_budget,
        "visited_count": solution.visited_count,
        "feasible": solution.feasible,
        "runtime_ms": round(runtime_ms, 4),
        "route": " -> ".join(map(str, solution.route)),
    }


def run_experiments(args: argparse.Namespace) -> pd.DataFrame:
    records = []

    for candidate_count in args.nodes:
        if candidate_count > 18:
            raise ValueError(
                "The exact solver is exponential. Use at most 18 candidates."
            )

        for instance_index in range(args.instances):
            instance_seed = args.seed + 10_000 * candidate_count + instance_index
            instance = generate_synthetic_instance(
                candidate_count=candidate_count,
                seed=instance_seed,
                time_budget=args.time_budget,
            )

            exact, exact_runtime = timed_solve(
                solve_exact_dynamic_programming,
                instance,
            )
            results = [(exact, exact_runtime)]

            for solver in SOLVERS[1:]:
                results.append(timed_solve(solver, instance))

            for solution, runtime_ms in results:
                records.append(
                    solution_record(
                        solution=solution,
                        runtime_ms=runtime_ms,
                        candidate_count=candidate_count,
                        instance_index=instance_index,
                        instance_seed=instance_seed,
                        time_budget=args.time_budget,
                        optimal_reward=exact.reward,
                    )
                )

    return pd.DataFrame.from_records(records)


def print_summary(results: pd.DataFrame) -> None:
    summary = (
        results.groupby(["candidate_count", "solver"], as_index=False)
        .agg(
            mean_reward=("reward", "mean"),
            mean_gap_percent=("optimality_gap_percent", "mean"),
            feasible_rate=("feasible", "mean"),
            mean_runtime_ms=("runtime_ms", "mean"),
        )
        .sort_values(["candidate_count", "mean_gap_percent"])
    )
    summary["feasible_rate"] = 100 * summary["feasible_rate"]
    print("\nRoute2Study baseline summary\n")
    print(summary.to_string(index=False, float_format=lambda value: f"{value:.3f}"))


def main() -> None:
    args = parse_arguments()
    results = run_experiments(args)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    results.to_csv(args.output, index=False)
    print_summary(results)
    print(f"\nSaved {len(results)} experiment rows to {args.output}")


if __name__ == "__main__":
    main()
