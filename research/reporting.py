"""Utilities for turning Route2Study experiment CSVs into dashboard data."""

from __future__ import annotations

from pathlib import Path

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
