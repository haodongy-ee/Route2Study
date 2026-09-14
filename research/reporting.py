"""Utilities for turning Route2Study experiment CSVs into dashboard data."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


REQUIRED_RESULT_COLUMNS = {
    "solver",
    "reward",
    "optimality_gap_percent",
    "feasible",
    "runtime_ms",
}

REQUIRED_SUMMARY_COLUMNS = {
    "solver",
    "scenarios",
    "mean_reward",
    "mean_gap_percent",
    "feasible_rate_percent",
    "mean_runtime_ms",
}

SOLVER_LABELS = {
    "exact_dynamic_programming": "Exact dynamic programming",
    "greedy_reward_per_minute": "Greedy reward/minute",
    "nearest": "Nearest feasible stop",
}


def solver_label(solver: str) -> str:
    """Return a readable label while preserving unknown future solvers."""

    return SOLVER_LABELS.get(solver, solver.replace("_", " ").title())


def _validate_columns(data: pd.DataFrame, required: set[str]) -> None:
    missing = required - set(data.columns)
    if missing:
        missing_text = ", ".join(sorted(missing))
        raise ValueError(f"Experiment data is missing columns: {missing_text}")
    if data.empty:
        raise ValueError("Experiment data is empty.")


def _coerce_feasible(values: pd.Series) -> pd.Series:
    """Normalize common CSV boolean representations to 0/1 values."""

    if pd.api.types.is_bool_dtype(values):
        return values.astype(float)

    normalized = values.astype(str).str.strip().str.lower()
    mapped = normalized.map(
        {
            "true": 1.0,
            "false": 0.0,
            "1": 1.0,
            "0": 0.0,
            "yes": 1.0,
            "no": 0.0,
        }
    )
    if mapped.isna().any():
        raise ValueError("The feasible column contains unsupported values.")
    return mapped


def summarize_results(results: pd.DataFrame) -> pd.DataFrame:
    """Aggregate one raw experiment row per solver and scenario."""

    _validate_columns(results, REQUIRED_RESULT_COLUMNS)
    clean = results.copy()
    for column in ("reward", "optimality_gap_percent", "runtime_ms"):
        clean[column] = pd.to_numeric(clean[column], errors="raise")
    clean["feasible_numeric"] = _coerce_feasible(clean["feasible"])

    summary = (
        clean.groupby("solver", as_index=False)
        .agg(
            scenarios=("solver", "size"),
            mean_reward=("reward", "mean"),
            mean_gap_percent=("optimality_gap_percent", "mean"),
            feasible_rate_percent=("feasible_numeric", "mean"),
            mean_runtime_ms=("runtime_ms", "mean"),
        )
        .sort_values(["mean_gap_percent", "mean_runtime_ms"])
        .reset_index(drop=True)
    )
    summary["feasible_rate_percent"] *= 100
    summary.insert(1, "method", summary["solver"].map(solver_label))
    return summary


def load_raw_summary(file_path: str | Path) -> pd.DataFrame:
    """Read a raw result CSV and return its aggregate summary."""

    return summarize_results(pd.read_csv(file_path))


def _bootstrap_mean_interval(
    values: pd.Series,
    rng: np.random.Generator,
    samples: int,
) -> tuple[float, float]:
    numeric = pd.to_numeric(values, errors="raise").to_numpy(dtype=float)
    if len(numeric) == 1:
        return float(numeric[0]), float(numeric[0])
    draws = rng.choice(numeric, size=(samples, len(numeric)), replace=True)
    means = draws.mean(axis=1)
    low, high = np.percentile(means, [2.5, 97.5])
    return float(low), float(high)


def summarize_results_with_uncertainty(
    results: pd.DataFrame,
    bootstrap_samples: int = 2000,
    seed: int = 2026,
) -> pd.DataFrame:
    """Report dispersion and reproducible 95% bootstrap confidence intervals."""

    _validate_columns(results, REQUIRED_RESULT_COLUMNS)
    if bootstrap_samples < 100:
        raise ValueError("bootstrap_samples must be at least 100")

    clean = results.copy()
    for column in ("reward", "optimality_gap_percent", "runtime_ms"):
        clean[column] = pd.to_numeric(clean[column], errors="raise")
    clean["feasible_numeric"] = _coerce_feasible(clean["feasible"])

    records = []
    for solver, group in clean.groupby("solver", sort=False):
        solver_seed = seed + sum(ord(character) for character in solver)
        rng = np.random.default_rng(solver_seed)
        reward_low, reward_high = _bootstrap_mean_interval(
            group["reward"], rng, bootstrap_samples
        )
        gap_low, gap_high = _bootstrap_mean_interval(
            group["optimality_gap_percent"], rng, bootstrap_samples
        )
        records.append(
            {
                "solver": solver,
                "method": solver_label(solver),
                "scenarios": len(group),
                "mean_reward": group["reward"].mean(),
                "reward_std": group["reward"].std(ddof=1),
                "reward_ci_low": reward_low,
                "reward_ci_high": reward_high,
                "mean_gap_percent": group["optimality_gap_percent"].mean(),
                "gap_std": group["optimality_gap_percent"].std(ddof=1),
                "gap_ci_low": gap_low,
                "gap_ci_high": gap_high,
                "feasible_rate_percent": 100 * group["feasible_numeric"].mean(),
                "mean_runtime_ms": group["runtime_ms"].mean(),
                "median_runtime_ms": group["runtime_ms"].median(),
                "p95_runtime_ms": group["runtime_ms"].quantile(0.95),
            }
        )

    return (
        pd.DataFrame.from_records(records)
        .sort_values(["mean_gap_percent", "median_runtime_ms"])
        .reset_index(drop=True)
    )


def load_raw_rigorous_summary(file_path: str | Path) -> pd.DataFrame:
    """Load raw results and include variability and uncertainty statistics."""

    return summarize_results_with_uncertainty(pd.read_csv(file_path))


def load_saved_summary(file_path: str | Path) -> pd.DataFrame:
    """Read a previously aggregated benchmark summary."""

    summary = pd.read_csv(file_path)
    _validate_columns(summary, REQUIRED_SUMMARY_COLUMNS)
    for column in (
        "scenarios",
        "mean_reward",
        "mean_gap_percent",
        "feasible_rate_percent",
        "mean_runtime_ms",
    ):
        summary[column] = pd.to_numeric(summary[column], errors="raise")
    summary = summary.sort_values(
        ["mean_gap_percent", "mean_runtime_ms"]
    ).reset_index(drop=True)
    summary.insert(1, "method", summary["solver"].map(solver_label))
    return summary
