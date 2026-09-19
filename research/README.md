# Route2Study Research Baselines

This folder starts the reproducible research track for Route2Study. It models
the project as a personalized, time-budgeted open orienteering problem:

- start from a residence, address, map pin, or current location;
- optionally visit useful campus locations;
- collect personalized utility from visited locations;
- reach the destination class before the time budget expires.

## Included baselines

1. `nearest`: visit the nearest feasible candidate.
2. `greedy_reward_per_minute`: prefer high personalized utility per added minute.
3. `exact_dynamic_programming`: calculate the optimum for small instances.

The exact method grows exponentially. It is a reference method for small
instances, not the final large-scale solver.

## Run the experiment

From `E:\Route2Study` in the `route2study` environment:

```powershell
python research\run_experiments.py
```

The script creates:

```text
research\results\baseline_results.csv
```

Quick test with fewer instances:

```powershell
python research\run_experiments.py --nodes 5 7 --instances 3
```

## Reported metrics

- reward: personalized utility collected by a route;
- optimality gap: reward lost relative to the exact solution;
- feasibility rate: fraction of routes that meet the time budget;
- study-plan rate: fraction that visit at least one study location;
- deadline slack: unused minutes remaining after reaching class;
- walking detour: extra walking time relative to going directly to class;
- runtime: computation time in milliseconds;
- walking/service time and number of visited candidates.

## Research roadmap

1. Validate these baselines on synthetic instances.
2. Build Penn instances from the OpenStreetMap walking network.
3. Reproduce an attention-based Orienteering Problem policy.
4. Add context such as preference, occupancy, weather, and uncertainty.
5. Evaluate utility, feasibility, optimality gap, runtime, and ablations.

Synthetic data is only for controlled algorithm testing. Claims about Penn
students require a documented real dataset or a clearly labeled user study.

## Penn walking-network experiments

The Penn experiment uses:

- `data/penn_walking_network.graphml` for pedestrian-network distances;
- `data/penn_locations.csv` for residences, academic buildings, and study spaces;
- `research/cache/penn_travel_minutes.csv` as a reusable all-pairs travel matrix;
- `research/cache/penn_location_snap_audit.csv` to document how far each
  building coordinate was from its matched network node.

Run a small validation first:

```powershell
python research\run_penn_experiments.py --quick
```

Then run all residence, classroom, preference, and time-budget combinations:

```powershell
python research\run_penn_experiments.py
```

For publication-style timing, use repeated measurements and warm-ups:

```powershell
python research\run_penn_experiments.py --timing-repeats 10 --warmup-runs 2 --order-seed 2026
```

Each scenario rotates solver order deterministically to reduce cache/order bias.
The raw CSV records median, mean, standard deviation, and P95 runtime together
with study-plan, slack, direct-route, and detour fields. A sidecar metadata JSON
records matrix preprocessing separately. The app reports reward/gap dispersion
and reproducible 95% bootstrap confidence intervals (2,000 resamples; seed 2026).

Use `--rebuild-matrix` after changing the graph or location coordinates.

The current preference scores are labeled `prototype_unvalidated`. They are
engineering placeholders, not measured student opinions. A publishable study
must replace or validate them using a documented survey, observational data,
or another defensible source.

## Streamlit benchmark dashboard

Run the main application and select **Research benchmark** in the top navigation:

```powershell
streamlit run app.py
```

The dashboard reports reward, optimality gap, feasibility, study-plan rate,
deadline slack, walking detour, uncertainty, and runtime for every solver. It
loads results in this order when available:

1. `research/results/penn_baseline_results.csv` (raw Penn experiment rows);
2. `research/results/penn_quick_summary.csv` (saved 12-scenario Penn pilot);
3. `research/results/baseline_results.csv` (raw synthetic experiment rows).

Runtime values are local wall-clock measurements and should only be compared
within the same run and hardware environment.
