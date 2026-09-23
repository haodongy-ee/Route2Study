# Route2Study

Route2Study is a Penn campus route and study planner built with Streamlit,
OpenStreetMap, and NetworkX. It recommends a feasible study stop between a
starting location and a class, then visualizes the walking route and timeline.

The project also includes a reproducible research benchmark for a personalized,
time-budgeted open orienteering formulation.

## Live App

[Open Route2Study](https://route2study.streamlit.app/)

Use the top navigation to switch between the personalized planner, **My
Routine**, and the research benchmark dashboard.

## Features

- Start from a campus building, street address, map pin, or browser location.
- Save a session-level routine with a preferred start, class building, study
  style, walking pace, minimum study block, transition buffer, and favorite
  study spaces.
- Load the saved routine in one tap or build a quick plan from the current
  Penn time.
- Route on the Penn-area OpenStreetMap pedestrian network.
- Rank study spaces by available study time, user preference, walking pace,
  favorites, opening status, and optional live crowd awareness.
- Check today's official Penn Libraries hours at the planned arrival time.
- Use anonymous crowd reports from the last two hours to avoid busy spaces.
- Explain why the top recommendation fits, visualize the time allocation, open
  the two-leg walk in Google Maps, and download the study block as a calendar
  event or text summary.
- Use a responsive planner, map, metrics, and navigation on mobile screens.
- Compare exact dynamic programming, reward-per-minute greedy, and nearest-stop
  solvers using reward, optimality gap, feasibility, study-plan rate, deadline
  slack, walking detour, runtime distributions, and reproducible 95% bootstrap
  confidence intervals.
- Reproduce synthetic and Penn walking-network experiments from command-line
  scripts.

## Run the app

From `E:\Route2Study` in the `route2study` Conda environment:

```powershell
python -m pip install -r requirements.txt
streamlit run app.py
```

The planner expects these local data files:

```text
data/penn_locations.csv
data/penn_walking_network.graphml
```

Use the top navigation to switch between **Plan**, **My routine**, and
**Research**. Routine settings are stored in the active Streamlit session; a
persistent account/database layer is intentionally left for the next product
phase.
The benchmark page can run without loading the large walking-network file.

## Reproduce the experiments

Synthetic baseline:

```powershell
python research\run_experiments.py
```

Penn quick validation:

```powershell
python research\run_penn_experiments.py --quick
```

Full Penn experiment:

```powershell
python research\run_penn_experiments.py --timing-repeats 10 --warmup-runs 2
```

The benchmark rotates solver timing order with a fixed seed, performs untimed
warm-ups, and records median, mean, standard deviation, and P95 runtime. The app
adds 95% bootstrap confidence intervals using 2,000 resamples and seed 2026.
Route outcomes distinguish simply reaching class from actually scheduling a
study stop. Walking-network preprocessing is saved separately in
`penn_baseline_results.metadata.json` and is not mixed into solver runtime.

The app automatically prefers `research/results/penn_baseline_results.csv`
when it exists. A checked-in `penn_quick_summary.csv` records the completed
12-scenario pilot benchmark.

## Tests

```powershell
python -m unittest discover -s tests -v
```

## Current research status

The exact solver supplies ground truth for small instances. The heuristic
baselines establish speed and solution-quality references for later learned
policies. Penn preference scores are currently prototype engineering values;
they are not claims about measured student behavior.

Penn Libraries hours come from the official daily hours page and are cached for
15 minutes. A September 2026 schedule is used only as a dated fallback when the
live page is unavailable. Crowding values are anonymous user reports, expire after two hours,
and reset when the Streamlit process restarts; `Unknown` means no recent report.

See [research/README.md](research/README.md) for the formulation and roadmap.
