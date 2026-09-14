"""Connect Route2Study research solvers to the Penn pedestrian network."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from research.orienteering import OrienteeringInstance


WALKING_SPEED_METERS_PER_MINUTE = 80.0
MAX_NETWORK_SNAP_METERS = 500.0

PREFERENCE_COLUMNS = {
    "Quiet": "quiet_score",
    "Collaborative": "collaborative_score",
    "Coffee nearby": "coffee_score",
    "Power outlets": "outlet_score",
    "No preference": None,
}

REQUIRED_LOCATION_COLUMNS = {
    "name",
    "latitude",
    "longitude",
    "category",
    "can_be_start",
    "can_be_class",
    "can_be_study",
    "quiet_score",
    "collaborative_score",
    "coffee_score",
    "outlet_score",
    "default_service_minutes",
}


def load_locations(path: Path) -> pd.DataFrame:
    locations = pd.read_csv(path)
    missing = REQUIRED_LOCATION_COLUMNS - set(locations.columns)
    if missing:
        raise ValueError(f"Missing location columns: {', '.join(sorted(missing))}")
    if locations["name"].duplicated().any():
        duplicates = locations.loc[locations["name"].duplicated(), "name"].tolist()
        raise ValueError(f"Duplicate location names: {duplicates}")
    return locations


def load_graph(path: Path):
    import osmnx as ox

    if not path.exists():
        raise FileNotFoundError(f"Penn walking graph not found: {path}")
    return ox.io.load_graphml(filepath=path)


def build_location_travel_matrix(
    graph,
    locations: pd.DataFrame,
    walking_speed: float = WALKING_SPEED_METERS_PER_MINUTE,
    max_snap_distance: float = MAX_NETWORK_SNAP_METERS,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return all-pairs walking minutes and a coordinate-to-network audit table."""

    import networkx as nx
    import osmnx as ox

    if walking_speed <= 0:
        raise ValueError("walking_speed must be positive")

    node_ids, snap_distances = ox.distance.nearest_nodes(
        graph,
        X=locations["longitude"].tolist(),
        Y=locations["latitude"].tolist(),
        return_dist=True,
    )

    audit = locations[["name", "category", "latitude", "longitude"]].copy()
    audit["network_node"] = list(node_ids)
    audit["snap_distance_meters"] = [round(float(value), 2) for value in snap_distances]
    audit["within_snap_limit"] = audit["snap_distance_meters"] <= max_snap_distance

    outside = audit.loc[~audit["within_snap_limit"], "name"].tolist()
    if outside:
        raise ValueError(
            "Locations outside the walking network coverage: " + ", ".join(outside)
        )

    names = locations["name"].tolist()
    node_by_name = dict(zip(names, node_ids))
    matrix = pd.DataFrame(index=names, columns=names, dtype=float)

    # Run Dijkstra once per unique source node instead of once per pair.
    shortest_from_node = {}
    for source_node in dict.fromkeys(node_ids):
        shortest_from_node[source_node] = nx.single_source_dijkstra_path_length(
            graph,
            source_node,
            weight="length",
        )

    for source_name in names:
        source_node = node_by_name[source_name]
        distance_lookup = shortest_from_node[source_node]

        for destination_name in names:
            destination_node = node_by_name[destination_name]
            distance_meters = distance_lookup.get(destination_node)
            if distance_meters is None:
                raise nx.NetworkXNoPath(
                    f"No walking route from {source_name} to {destination_name}"
                )
            matrix.loc[source_name, destination_name] = (
                float(distance_meters) / walking_speed
            )

    matrix.index.name = "location"
    return matrix.round(4), audit


def preference_prize(row: pd.Series, preference: str) -> float:
    if preference not in PREFERENCE_COLUMNS:
        raise ValueError(f"Unknown preference: {preference}")

    preference_column = PREFERENCE_COLUMNS[preference]
    if preference_column is None:
        match = row[
            [
                "quiet_score",
                "collaborative_score",
                "coffee_score",
                "outlet_score",
            ]
        ].mean()
    else:
        match = row[preference_column]

    # The primary preference dominates; outlets add a small general benefit.
    return round(2.0 * float(match) + 0.2 * float(row["outlet_score"]), 4)


def create_penn_instance(
    locations: pd.DataFrame,
    travel_matrix: pd.DataFrame,
    start_name: str,
    destination_name: str,
    preference: str,
    time_budget: float,
) -> tuple[OrienteeringInstance, dict[int, str]]:
    """Create one solver instance and its node-to-building mapping."""

    lookup = locations.set_index("name")
    for name in (start_name, destination_name):
        if name not in lookup.index:
            raise KeyError(f"Unknown Penn location: {name}")

    candidates = locations.loc[locations["can_be_study"] == 1].copy()
    candidates = candidates.loc[
        ~candidates["name"].isin([start_name, destination_name])
    ].reset_index(drop=True)

    ordered_names = [start_name, *candidates["name"].tolist(), destination_name]
    travel_minutes = tuple(
        tuple(float(travel_matrix.loc[first, second]) for second in ordered_names)
        for first in ordered_names
    )
    prizes = tuple(
        preference_prize(row, preference)
        for _, row in candidates.iterrows()
    )
    service_minutes = tuple(
        float(value) for value in candidates["default_service_minutes"]
    )

    instance = OrienteeringInstance(
        travel_minutes=travel_minutes,
        prizes=prizes,
        service_minutes=service_minutes,
        time_budget=float(time_budget),
        name=(
            f"penn_{start_name}_to_{destination_name}_"
            f"{preference}_{int(time_budget)}"
        ),
    )
    node_names = {index: name for index, name in enumerate(ordered_names)}
    return instance, node_names


def save_matrix_and_audit(
    matrix: pd.DataFrame,
    audit: pd.DataFrame,
    matrix_path: Path,
    audit_path: Path,
) -> None:
    matrix_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    matrix.to_csv(matrix_path)
    audit.to_csv(audit_path, index=False)
