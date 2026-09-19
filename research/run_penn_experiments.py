"""Benchmark Route2Study solvers on the real Penn walking network.

From the project root:
    python research/run_penn_experiments.py --quick
    python research/run_penn_experiments.py
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from research.orienteering import (  # noqa: E402
    solve_exact_dynamic_programming,
    solve_greedy,
    solve_nearest,
)
from research.penn_network import (  # noqa: E402
    PREFERENCE_COLUMNS,
    build_location_travel_matrix,
    create_penn_instance,
    load_graph,
    load_locations,
    save_matrix_and_audit,
)


DATA_DIR = PROJECT_ROOT / "data"
RESEARCH_DIR = PROJECT_ROOT / "research"
LOCATION_FILE = DATA_DIR / "penn_locations.csv"
GRAPH_FILE = DATA_DIR / "penn_walking_network.graphml"
MATRIX_FILE = RESEARCH_DIR / "cache" / "penn_travel_minutes.csv"
AUDIT_FILE = RESEARCH_DIR / "cache" / "penn_location_snap_audit.csv"
DEFAULT_OUTPUT = RESEARCH_DIR / "results" / "penn_baseline_results.csv"

SOLVERS = (
    solve_exact_dynamic_programming,
    solve_greedy,
    solve_nearest,
)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run routing baselines on the Penn pedestrian network.",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Run a small smoke-test subset before the full experiment.",
    )
    parser.add_argument(
        "--rebuild-matrix",
        action="store_true",
        help="Recompute cached Penn pairwise walking times.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
    )
    parser.add_argument(
        "--timing-repeats",
        type=int,
        default=5,
        help="Timed repetitions per solver/scenario; the median is reported.",
    )
    parser.add_argument(
        "--warmup-runs",
        type=int,
        default=1,
        help="Untimed warm-up calls per solver/scenario.",
    )
    parser.add_argument(
        "--order-seed",
        type=int,
        default=2026,
        help="Seed used to rotate solver timing order across scenarios.",
    )
    return parser.parse_args()


def load_or_build_matrix(
    locations: pd.DataFrame,
    rebuild: bool,
) -> tuple[pd.DataFrame, str, float]:
    started = time.perf_counter_ns()
    if MATRIX_FILE.exists() and not rebuild:
        matrix = pd.read_csv(MATRIX_FILE, index_col="location")
        elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
        return matrix, "cached_csv", elapsed_ms

    graph = load_graph(GRAPH_FILE)
    matrix, audit = build_location_travel_matrix(graph, locations)
    save_matrix_and_audit(matrix, audit, MATRIX_FILE, AUDIT_FILE)
    elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
    return matrix, "rebuilt_from_graph", elapsed_ms


def route_names(solution, node_names: dict[int, str]) -> str:
    return " -> ".join(node_names[node] for node in solution.route)


def benchmark_solver(solver, instance, warmups: int, repeats: int):
    """Warm up a solver and return its solution plus robust timing samples."""

    if repeats < 1 or warmups < 0:
        raise ValueError("timing repeats must be >= 1 and warmups must be >= 0")
    for _ in range(warmups):
        solver(instance)

    timings = []
    solution = None
    for _ in range(repeats):
        started = time.perf_counter_ns()
        solution = solver(instance)
        timings.append((time.perf_counter_ns() - started) / 1_000_000)

    ordered = sorted(timings)
    p95_index = min(len(ordered) - 1, round(0.95 * (len(ordered) - 1)))
    return solution, {
        "runtime_ms": statistics.median(timings),
        "runtime_mean_ms": statistics.fmean(timings),
        "runtime_p95_ms": ordered[p95_index],
        "runtime_std_ms": statistics.stdev(timings) if len(timings) > 1 else 0.0,
    }


def operational_metrics(solution, time_budget: float, direct_travel_minutes: float):
    """Measure whether a useful study plan was made and its routing cost."""

    study_plan = solution.visited_count > 0 and solution.service_minutes > 0
    deadline_slack = time_budget - solution.total_minutes
    walking_detour = max(
        0.0,
        solution.travel_minutes - direct_travel_minutes,
    )
    detour_percent = (
        100 * walking_detour / direct_travel_minutes
        if direct_travel_minutes > 0
        else 0.0
    )
    return {
        "study_plan": study_plan,
        "deadline_slack_minutes": round(deadline_slack, 4),
        "direct_travel_minutes": round(direct_travel_minutes, 4),
        "walking_detour_minutes": round(walking_detour, 4),
        "walking_detour_percent": round(detour_percent, 4),
    }


def run(args: argparse.Namespace) -> pd.DataFrame:
    if args.timing_repeats < 1 or args.warmup_runs < 0:
        raise ValueError("--timing-repeats must be >= 1 and --warmup-runs >= 0")
    preprocessing_started = time.perf_counter_ns()
    locations = load_locations(LOCATION_FILE)
    locations_loaded_ms = (
        time.perf_counter_ns() - preprocessing_started
    ) / 1_000_000
    travel_matrix, matrix_source, matrix_setup_ms = load_or_build_matrix(
        locations, args.rebuild_matrix
    )
    preprocessing_ms = locations_loaded_ms + matrix_setup_ms

    residences = locations.loc[
        locations["category"] == "residence", "name"
    ].tolist()
    destinations = locations.loc[
        locations["can_be_class"] == 1, "name"
    ].tolist()
    preferences = list(PREFERENCE_COLUMNS)
    budgets = [45.0, 60.0, 90.0]

    if args.quick:
        residences = residences[:2]
        destinations = destinations[:3]
        preferences = ["Quiet"]
        budgets = [45.0, 60.0]

    records = []
    scenario_index = 0

    for start_name in residences:
        for destination_name in destinations:
            for preference in preferences:
                for time_budget in budgets:
                    scenario_index += 1
                    instance, node_names = create_penn_instance(
                        locations=locations,
                        travel_matrix=travel_matrix,
                        start_name=start_name,
                        destination_name=destination_name,
                        preference=preference,
                        time_budget=time_budget,
                    )
                    direct_travel_minutes = float(
                        travel_matrix.loc[start_name, destination_name]
                    )

                    solver_order = list(SOLVERS)
                    random.Random(args.order_seed + scenario_index).shuffle(solver_order)
                    scenario_solutions = {}
                    for solver in solver_order:
                        solution, timing = benchmark_solver(
                            solver,
                            instance,
                            warmups=args.warmup_runs,
                            repeats=args.timing_repeats,
                        )
                        scenario_solutions[solver] = (solution, timing)

                    optimal_reward = scenario_solutions[
                        solve_exact_dynamic_programming
                    ][0].reward
                    for solver in SOLVERS:
                        solution, timing = scenario_solutions[solver]
                        if optimal_reward > 0:
                            gap = 100 * (
                                optimal_reward - solution.reward
                            ) / optimal_reward
                        else:
                            gap = 0.0

                        outcome = operational_metrics(
                            solution,
                            time_budget,
                            direct_travel_minutes,
                        )

                        records.append(
                            {
                                "scenario_index": scenario_index,
                                "start": start_name,
                                "destination": destination_name,
                                "preference": preference,
                                "time_budget": time_budget,
                                "solver": solution.solver,
                                "reward": solution.reward,
                                "optimal_reward": optimal_reward,
                                "optimality_gap_percent": round(max(0.0, gap), 4),
                                "travel_minutes": solution.travel_minutes,
                                "study_minutes": solution.service_minutes,
                                "total_minutes": solution.total_minutes,
                                "visited_count": solution.visited_count,
                                "feasible": solution.feasible,
                                **outcome,
                                "runtime_ms": round(timing["runtime_ms"], 4),
                                "runtime_mean_ms": round(timing["runtime_mean_ms"], 4),
                                "runtime_p95_ms": round(timing["runtime_p95_ms"], 4),
                                "runtime_std_ms": round(timing["runtime_std_ms"], 4),
                                "timing_repeats": args.timing_repeats,
                                "order_seed": args.order_seed,
                                "route": route_names(solution, node_names),
                            }
                        )

    results = pd.DataFrame.from_records(records)
    results.attrs.update(
        {
            "preprocessing_ms": preprocessing_ms,
            "locations_load_ms": locations_loaded_ms,
            "matrix_setup_ms": matrix_setup_ms,
            "matrix_source": matrix_source,
            "timing_repeats": args.timing_repeats,
            "warmup_runs": args.warmup_runs,
            "order_seed": args.order_seed,
        }
    )
    return results


def print_summary(results: pd.DataFrame) -> None:
    summary = (
        results.groupby("solver", as_index=False)
        .agg(
            scenarios=("scenario_index", "count"),
            mean_reward=("reward", "mean"),
            mean_gap_percent=("optimality_gap_percent", "mean"),
            feasible_rate=("feasible", "mean"),
            study_plan_rate=("study_plan", "mean"),
            mean_deadline_slack_minutes=("deadline_slack_minutes", "mean"),
            mean_walking_detour_minutes=("walking_detour_minutes", "mean"),
            mean_runtime_ms=("runtime_ms", "mean"),
        )
        .sort_values("mean_gap_percent")
    )
    summary["feasible_rate"] *= 100
    summary["study_plan_rate"] *= 100
    print("\nPenn walking-network experiment summary\n")
    print(summary.to_string(index=False, float_format=lambda value: f"{value:.3f}"))


def main() -> None:
    args = parse_arguments()
    results = run(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    results.to_csv(args.output, index=False)
    metadata_path = args.output.with_suffix(".metadata.json")
    metadata = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "rows": len(results),
        "scenarios_per_solver": int(results["scenario_index"].nunique()),
        **results.attrs,
    }
    metadata_path.write_text(
        json.dumps(metadata, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print_summary(results)
    print(f"\nSaved {len(results)} rows to {args.output}")
    print(f"Travel matrix: {MATRIX_FILE}")
    print(f"Location audit: {AUDIT_FILE}")
    print(f"Experiment metadata: {metadata_path}")


if __name__ == "__main__":
    main()
