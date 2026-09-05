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
