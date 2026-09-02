from pathlib import Path

import osmnx as ox


PROJECT_ROOT = Path(__file__).resolve().parent
OUTPUT_FILE = PROJECT_ROOT / "data" / "penn_walking_network.graphml"

# Approximate center of the University of Pennsylvania campus.
CAMPUS_CENTER = (39.9522, -75.1930)

# Download a walking network within 1,600 meters of campus center.
NETWORK_RADIUS_METERS = 3000


def main():
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    ox.settings.use_cache = True
    ox.settings.log_console = True

    print("Downloading the Penn campus walking network...")

    graph = ox.graph.graph_from_point(
        CAMPUS_CENTER,
        dist=NETWORK_RADIUS_METERS,
        network_type="walk",
        simplify=True,
    )

    ox.io.save_graphml(graph, filepath=OUTPUT_FILE)

    print("Walking network saved successfully.")
    print(f"File: {OUTPUT_FILE}")
    print(f"Nodes: {len(graph.nodes):,}")
    print(f"Edges: {len(graph.edges):,}")


if __name__ == "__main__":
    main()