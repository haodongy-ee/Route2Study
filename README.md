# Route2Study

Route2Study is a Penn campus route and study planner built with Streamlit,
OpenStreetMap, and NetworkX. It recommends a feasible study stop between a
starting location and a class, then visualizes the walking route and timeline.

The project also includes a reproducible research benchmark for a personalized,
time-budgeted open orienteering formulation.

## Live App

[Open Route2Study](https://route2study.streamlit.app/)

Use the top navigation to switch between the interactive route planner and the
research benchmark dashboard.

## Features

- Start from a campus building, street address, map pin, or browser location.
- Route on the Penn-area OpenStreetMap pedestrian network.
- Rank study spaces by available study time and user preference.
- Check today's official Penn Libraries hours at the planned arrival time.
- Use anonymous crowd reports from the last two hours to avoid busy spaces.
- Use a responsive planner, map, metrics, and navigation on mobile screens.
- Compare exact dynamic programming, reward-per-minute greedy, and nearest-stop
  solvers using reward, optimality gap, feasibility, runtime distributions, and
  reproducible 95% bootstrap confidence intervals.
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

Use the sidebar to switch between **Plan a route** and **Research benchmark**.
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
15 minutes. Crowding values are anonymous user reports, expire after two hours,
and reset when the Streamlit process restarts; `Unknown` means no recent report.

See [research/README.md](research/README.md) for the formulation and roadmap.
