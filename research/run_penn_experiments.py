"""Benchmark Route2Study solvers on the real Penn walking network.

From the project root:
    python research/run_penn_experiments.py --quick
    python research/run_penn_experiments.py
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
    return parser.parse_args()


def load_or_build_matrix(
    locations: pd.DataFrame,
    rebuild: bool,
) -> pd.DataFrame:
    if MATRIX_FILE.exists() and not rebuild:
        return pd.read_csv(MATRIX_FILE, index_col="location")

    graph = load_graph(GRAPH_FILE)
    matrix, audit = build_location_travel_matrix(graph, locations)
    save_matrix_and_audit(matrix, audit, MATRIX_FILE, AUDIT_FILE)
    return matrix


def route_names(solution, node_names: dict[int, str]) -> str:
    return " -> ".join(node_names[node] for node in solution.route)


def run(args: argparse.Namespace) -> pd.DataFrame:
    locations = load_locations(LOCATION_FILE)
    travel_matrix = load_or_build_matrix(locations, args.rebuild_matrix)

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

                    scenario_solutions = []
                    for solver in SOLVERS:
                        started = time.perf_counter()
                        solution = solver(instance)
                        runtime_ms = (time.perf_counter() - started) * 1000
                        scenario_solutions.append((solution, runtime_ms))

                    optimal_reward = scenario_solutions[0][0].reward
                    for solution, runtime_ms in scenario_solutions:
                        if optimal_reward > 0:
                            gap = 100 * (
                                optimal_reward - solution.reward
                            ) / optimal_reward
                        else:
                            gap = 0.0

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
                                "runtime_ms": round(runtime_ms, 4),
                                "route": route_names(solution, node_names),
                            }
                        )

    return pd.DataFrame.from_records(records)


def print_summary(results: pd.DataFrame) -> None:
    summary = (
        results.groupby("solver", as_index=False)
        .agg(
            scenarios=("scenario_index", "count"),
            mean_reward=("reward", "mean"),
            mean_gap_percent=("optimality_gap_percent", "mean"),
            feasible_rate=("feasible", "mean"),
            mean_runtime_ms=("runtime_ms", "mean"),
        )
        .sort_values("mean_gap_percent")
    )
    summary["feasible_rate"] *= 100
    print("\nPenn walking-network experiment summary\n")
    print(summary.to_string(index=False, float_format=lambda value: f"{value:.3f}"))


def main() -> None:
    args = parse_arguments()
    results = run(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    results.to_csv(args.output, index=False)
    print_summary(results)
    print(f"\nSaved {len(results)} rows to {args.output}")
    print(f"Travel matrix: {MATRIX_FILE}")
    print(f"Location audit: {AUDIT_FILE}")


if __name__ == "__main__":
    main()
