import html
import math
from datetime import date, datetime, time
from pathlib import Path

import folium
import networkx as nx
import osmnx as ox
import pandas as pd
import streamlit as st
from geopy.exc import GeocoderServiceError, GeocoderTimedOut
from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter
from streamlit_folium import st_folium
from streamlit_geolocation import streamlit_geolocation

from research.reporting import load_raw_summary, load_saved_summary


st.set_page_config(page_title="Route2Study", layout="wide")

PROJECT_ROOT = Path(__file__).resolve().parent
DATA_FILE = PROJECT_ROOT / "data" / "penn_locations.csv"
NETWORK_FILE = PROJECT_ROOT / "data" / "penn_walking_network.graphml"
RESULTS_DIR = PROJECT_ROOT / "research" / "results"

CAMPUS_CENTER = (39.9522, -75.1930)
WALKING_SPEED_METERS_PER_MINUTE = 80
TRANSITION_BUFFER_MINUTES = 10
MINIMUM_STUDY_MINUTES = 15
MAX_NETWORK_SNAP_METERS = 500

REQUIRED_COLUMNS = {
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
}

PREFERENCE_COLUMNS = {
    "Quiet": "quiet_score",
    "Collaborative": "collaborative_score",
    "Coffee nearby": "coffee_score",
    "Power outlets": "outlet_score",
}


def render_research_benchmark():
    """Render reproducible solver comparisons from saved experiment results."""

    st.header("Research Benchmark")
    st.write(
        "Compare the exact reference solver with two fast heuristics on "
        "time-budgeted campus study-planning problems."
    )

    benchmark_options = {}
    penn_raw = RESULTS_DIR / "penn_baseline_results.csv"
    penn_summary = RESULTS_DIR / "penn_quick_summary.csv"
    synthetic_raw = RESULTS_DIR / "baseline_results.csv"

    if penn_raw.exists():
        benchmark_options["Penn walking network · raw experiment"] = (
            "raw",
            penn_raw,
        )
    if penn_summary.exists():
        benchmark_options["Penn walking network · 12-scenario quick run"] = (
            "summary",
            penn_summary,
        )
    if synthetic_raw.exists():
        benchmark_options["Synthetic benchmark · 30 scenarios per solver"] = (
            "raw",
            synthetic_raw,
        )

    if not benchmark_options:
        st.warning(
            "No benchmark CSV was found. Run "
            "`python research/run_penn_experiments.py --quick` first."
        )
        return

    selected_name = st.selectbox(
        "Experiment dataset",
        list(benchmark_options),
    )
    result_kind, result_path = benchmark_options[selected_name]

    try:
        if result_kind == "raw":
            summary = load_raw_summary(result_path)
        else:
            summary = load_saved_summary(result_path)
    except (OSError, ValueError, pd.errors.ParserError) as error:
        st.error(f"Could not load experiment results: {error}")
        return

    exact_rows = summary.loc[
        summary["solver"] == "exact_dynamic_programming"
    ]
    heuristic_rows = summary.loc[
        summary["solver"] != "exact_dynamic_programming"
    ]
    fastest = summary.loc[summary["mean_runtime_ms"].idxmin()]
    best_heuristic = (
        heuristic_rows.sort_values(
            ["mean_gap_percent", "mean_runtime_ms"]
        ).iloc[0]
        if not heuristic_rows.empty
        else summary.iloc[0]
    )

    metric_1, metric_2, metric_3, metric_4 = st.columns(4)
    metric_1.metric("Methods", len(summary))
    metric_2.metric("Scenarios / method", int(summary["scenarios"].max()))
    metric_3.metric("Best heuristic gap", f"{best_heuristic['mean_gap_percent']:.2f}%")
    metric_4.metric("Fastest method", fastest["method"])

    if not exact_rows.empty:
        exact_reward = exact_rows.iloc[0]["mean_reward"]
        st.caption(
            f"Exact-reference mean reward: {exact_reward:.3f}. "
            "Runtime is local wall-clock time and is hardware-dependent."
        )

    chart_left, chart_right = st.columns(2)
    chart_data = summary.set_index("method")
    with chart_left:
        st.subheader("Mean Reward")
        st.bar_chart(chart_data[["mean_reward"]])
    with chart_right:
        st.subheader("Mean Optimality Gap (%)")
        st.bar_chart(chart_data[["mean_gap_percent"]])

    chart_left, chart_right = st.columns(2)
    with chart_left:
        st.subheader("Feasibility Rate (%)")
        st.bar_chart(chart_data[["feasible_rate_percent"]])
    with chart_right:
        st.subheader("Mean Runtime (ms)")
        st.bar_chart(chart_data[["mean_runtime_ms"]])

    display = summary[
        [
            "method",
            "scenarios",
            "mean_reward",
            "mean_gap_percent",
            "feasible_rate_percent",
            "mean_runtime_ms",
        ]
    ].copy()
    display.columns = [
        "Method",
        "Scenarios",
        "Mean reward",
        "Gap (%)",
        "Feasible (%)",
        "Runtime (ms)",
    ]
    for column in ("Mean reward", "Gap (%)", "Feasible (%)", "Runtime (ms)"):
        display[column] = display[column].round(3)

    st.subheader("Summary Table")
    st.dataframe(display, width="stretch", hide_index=True)
    st.info(
        "The Penn preference scores are prototype engineering values, not "
        "survey-validated student ratings. Treat these results as an "
        "algorithm benchmark rather than a user-behavior claim."
    )


@st.cache_data
def load_locations(file_path):
    if not file_path.exists():
        raise FileNotFoundError(f"Location data was not found at: {file_path}")

    data = pd.read_csv(file_path)
    missing_columns = REQUIRED_COLUMNS - set(data.columns)

    if missing_columns:
        missing = ", ".join(sorted(missing_columns))
        raise ValueError(f"Missing CSV columns: {missing}")

    return data


@st.cache_resource
def load_walking_network(file_path):
    if not file_path.exists():
        raise FileNotFoundError(f"Walking network was not found at: {file_path}")

    return ox.io.load_graphml(filepath=file_path)


@st.cache_data(ttl=86400, show_spinner=False)
def geocode_address(address_query):
    """Convert one user-submitted Philadelphia address to coordinates."""

    geolocator = Nominatim(
        user_agent=(
            "Route2Study/1.0 "
            "(https://github.com/haodongy-ee/Route2Study)"
        )
    )
    geocode = RateLimiter(
        geolocator.geocode,
        min_delay_seconds=1,
        swallow_exceptions=False,
    )
    result = geocode(
        address_query,
        exactly_one=True,
        country_codes="us",
        viewbox=[(39.85, -75.35), (40.10, -74.95)],
        bounded=True,
        timeout=10,
    )

    if result is None:
        return None

    return {
        "query": address_query,
        "label": result.address,
        "latitude": float(result.latitude),
        "longitude": float(result.longitude),
    }


def nearest_network_distance(graph, location):
    _, distance = ox.distance.nearest_nodes(
        graph,
        X=location["longitude"],
        Y=location["latitude"],
        return_dist=True,
    )
    return float(distance)


def calculate_network_route(graph, location_1, location_2):
    """Calculate a shortest route on the pedestrian street graph."""

    origin_node = ox.distance.nearest_nodes(
        graph,
        X=location_1["longitude"],
        Y=location_1["latitude"],
    )
    destination_node = ox.distance.nearest_nodes(
        graph,
        X=location_2["longitude"],
        Y=location_2["latitude"],
    )

    if origin_node == destination_node:
        return {
            "route_nodes": [origin_node],
            "distance_meters": 0,
            "walking_minutes": 0,
        }

    try:
        route_nodes = nx.shortest_path(
            graph,
            source=origin_node,
            target=destination_node,
            weight="length",
        )
    except nx.NetworkXNoPath:
        return None

    route_edges = ox.routing.route_to_gdf(graph, route_nodes, weight="length")
    distance_meters = float(route_edges["length"].sum())
    walking_minutes = math.ceil(
        distance_meters / WALKING_SPEED_METERS_PER_MINUTE
    )

    return {
        "route_nodes": route_nodes,
        "distance_meters": round(distance_meters),
        "walking_minutes": walking_minutes,
    }


def preference_score(location, preference):
    if preference == "No preference":
        return (
            location["quiet_score"]
            + location["collaborative_score"]
            + location["coffee_score"]
            + location["outlet_score"]
        ) / 4

    return location[PREFERENCE_COLUMNS[preference]]


def recommend_study_spaces(
    graph,
    start_location,
    destination_location,
    available_minutes,
    preference,
    location_lookup,
    study_location_names,
):
    recommendations = []

    for study_name in study_location_names:
        study_location = location_lookup[study_name]
        route_to_study = calculate_network_route(
            graph, start_location, study_location
        )
        route_to_class = calculate_network_route(
            graph, study_location, destination_location
        )

        if route_to_study is None or route_to_class is None:
            continue

        walk_to_study = route_to_study["walking_minutes"]
        walk_to_class = route_to_class["walking_minutes"]
        total_walking = walk_to_study + walk_to_class
        total_distance = (
            route_to_study["distance_meters"]
            + route_to_class["distance_meters"]
        )
        study_minutes = (
            available_minutes - total_walking - TRANSITION_BUFFER_MINUTES
        )

        if study_minutes < MINIMUM_STUDY_MINUTES:
            continue

        match_score = preference_score(study_location, preference)
        final_score = (
            study_minutes
            + 15 * match_score
            + 2 * study_location["outlet_score"]
            - 0.5 * total_walking
        )

        recommendations.append(
            {
                "name": study_name,
                "walk_to_study": walk_to_study,
                "walk_to_class": walk_to_class,
                "total_walking": total_walking,
                "total_distance": total_distance,
                "study_minutes": study_minutes,
                "preference_match": round(match_score, 1),
                "final_score": round(final_score, 1),
                "route_to_study": route_to_study,
                "route_to_class": route_to_class,
            }
        )

    return sorted(
        recommendations,
        key=lambda item: item["final_score"],
        reverse=True,
    )


def add_marker(campus_map, location, label, color, tooltip):
    folium.Marker(
        location=[location["latitude"], location["longitude"]],
        popup=label,
        tooltip=tooltip,
        icon=folium.Icon(color=color),
    ).add_to(campus_map)


def add_route_line(campus_map, graph, route_result, color, tooltip):
    if not route_result:
        return

    route_coordinates = [
        (graph.nodes[node]["y"], graph.nodes[node]["x"])
        for node in route_result["route_nodes"]
    ]

    if len(route_coordinates) >= 2:
        folium.PolyLine(
            locations=route_coordinates,
            color=color,
            weight=6,
            opacity=0.9,
            tooltip=tooltip,
        ).add_to(campus_map)


def create_route_map(
    graph,
    start_location,
    start_label,
    destination_location,
    destination_label,
    study_location=None,
    study_label=None,
    first_route=None,
    second_route=None,
):
    route_map = folium.Map(
        location=CAMPUS_CENTER,
        zoom_start=15,
        tiles="OpenStreetMap",
    )

    add_marker(route_map, start_location, start_label, "green", "Starting point")
    add_marker(
        route_map,
        destination_location,
        destination_label,
        "red",
        "Destination class",
    )

    marker_points = [
        [start_location["latitude"], start_location["longitude"]],
        [destination_location["latitude"], destination_location["longitude"]],
    ]

    if study_location and study_label:
        add_marker(
            route_map,
            study_location,
            study_label,
            "blue",
            "Recommended study location",
        )
        marker_points.append(
            [study_location["latitude"], study_location["longitude"]]
        )

    first_tooltip = (
        "To study space" if study_location else "Direct route to class"
    )
    add_route_line(
        route_map, graph, first_route, "#2563EB", first_tooltip
    )
    add_route_line(route_map, graph, second_route, "#7C3AED", "To class")
    route_map.fit_bounds(marker_points, padding=(40, 40))
    return route_map


def create_pin_picker(existing_pin=None):
    center = CAMPUS_CENTER
    if existing_pin:
        center = (existing_pin["latitude"], existing_pin["longitude"])

    picker_map = folium.Map(
        location=center,
        zoom_start=15,
        tiles="OpenStreetMap",
    )

    if existing_pin:
        add_marker(
            picker_map,
            existing_pin,
            "Selected starting point",
            "green",
            "Selected starting point",
        )

    folium.LatLngPopup().add_to(picker_map)
    return picker_map


st.markdown(
    """
    <style>
        .block-container {
            max-width: 1280px;
            padding-top: 2rem;
            padding-bottom: 3rem;
        }
        .hero {
            padding: 30px;
            border-radius: 20px;
            color: white;
            background: linear-gradient(120deg, #4338CA, #2563EB, #0891B2);
            margin-bottom: 25px;
            box-shadow: 0 10px 30px rgba(37, 99, 235, 0.18);
        }
        .hero h1 { margin: 0; font-size: 44px; }
        .hero p { margin: 8px 0 0 0; font-size: 18px; }
        .recommendation-card {
            padding: 22px;
            border: 1px solid #BFDBFE;
            border-left: 7px solid #2563EB;
            border-radius: 14px;
            background: #EFF6FF;
            margin: 12px 0 22px 0;
        }
        .recommendation-card h3 {
            margin: 0 0 8px 0;
            color: #1E3A8A;
        }
        .recommendation-card p { margin: 4px 0; color: #1F2937; }
    </style>
    <div class="hero">
        <h1>Route2Study</h1>
        <p>Start anywhere near Penn and turn free time into study time.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    app_view = st.radio(
        "Route2Study view",
        ["Plan a route", "Research benchmark"],
    )

if app_view == "Research benchmark":
    render_research_benchmark()
    st.stop()


try:
    locations_df = load_locations(DATA_FILE)
    walking_graph = load_walking_network(NETWORK_FILE)
except (FileNotFoundError, ValueError) as error:
    st.error(str(error))
    st.info(
        "Confirm that data/penn_locations.csv and "
        "data/penn_walking_network.graphml both exist."
    )
    st.stop()

location_lookup = locations_df.set_index("name").to_dict(orient="index")
start_location_names = locations_df.loc[
    locations_df["can_be_start"] == 1, "name"
].tolist()
class_location_names = locations_df.loc[
    locations_df["can_be_class"] == 1, "name"
].tolist()
study_location_names = locations_df.loc[
    locations_df["can_be_study"] == 1, "name"
].tolist()

start_location = None
start_label = None
location_accuracy = None


with st.sidebar:
    st.header("Plan Your Day")
    start_mode = st.selectbox(
        "Starting point method",
        [
            "Campus building",
            "Street address",
            "Drop a pin",
            "Current location",
        ],
    )

    if start_mode == "Campus building":
        start_label = st.selectbox(
            "Starting building or residence",
            start_location_names,
            format_func=lambda name: (
                f"{name} · {location_lookup[name]['category'].title()}"
            ),
        )
        start_location = location_lookup[start_label]

    elif start_mode == "Street address":
        address_query = st.text_input(
            "Starting address",
            placeholder="3900 Chestnut Street, Philadelphia, PA",
        ).strip()

        if st.button("Find address", width="stretch"):
            if not address_query:
                st.warning("Enter an address first.")
            else:
                try:
                    with st.spinner("Finding address..."):
                        result = geocode_address(address_query)

                    if result is None:
                        st.session_state.pop("address_location", None)
                        st.error("Address not found near Philadelphia.")
                    else:
                        st.session_state.address_location = result
                except (GeocoderTimedOut, GeocoderServiceError):
                    st.error(
                        "The address service is temporarily unavailable. "
                        "Try again or use a map pin."
                    )

        saved_address = st.session_state.get("address_location")
        if saved_address and saved_address.get("query") == address_query:
            start_location = saved_address
            start_label = saved_address["label"]
            st.success(f"Found: {start_label}")

        st.caption(
            "Do not include an apartment or room number. "
            "Address searches use OpenStreetMap Nominatim."
        )

    elif start_mode == "Drop a pin":
        saved_pin = st.session_state.get("pinned_location")
        if saved_pin:
            start_location = saved_pin
            start_label = "Pinned starting point"
            st.success("A starting point is selected on the map.")
        else:
            st.info("Use the map in the main panel to select a point.")

    else:
        st.caption("Press the location button below and allow browser access.")
        current_location = streamlit_geolocation()

        if (
            isinstance(current_location, dict)
            and current_location.get("latitude") is not None
            and current_location.get("longitude") is not None
        ):
            st.session_state.current_location = current_location

        saved_current_location = st.session_state.get("current_location")
        if saved_current_location:
            start_location = {
                "latitude": float(saved_current_location["latitude"]),
                "longitude": float(saved_current_location["longitude"]),
            }
            start_label = "Current location"
            location_accuracy = saved_current_location.get("accuracy")
            st.success("Current location received.")

    available_from = st.time_input("Available from", value=time(11, 30))
    destination_label = st.selectbox(
        "Destination class",
        class_location_names,
        index=min(1, len(class_location_names) - 1),
        format_func=lambda name: f"{name} · Academic",
    )
    class_start_time = st.time_input("Class starts", value=time(14, 0))
    study_preference = st.selectbox(
        "Study preference",
        [
            "Quiet",
            "Collaborative",
            "Coffee nearby",
            "Power outlets",
            "No preference",
        ],
    )


if start_mode == "Drop a pin":
    st.subheader("Choose Your Starting Point")
    st.write("Click anywhere on the map to place the starting pin.")
    existing_pin = st.session_state.get("pinned_location")
    picker_map = create_pin_picker(existing_pin)
    picker_result = st_folium(
        picker_map,
        width=1100,
        height=390,
        key="start_location_picker",
        returned_objects=["last_clicked"],
    )
    clicked_point = picker_result.get("last_clicked") if picker_result else None

    if clicked_point:
        new_pin = {
            "latitude": float(clicked_point["lat"]),
            "longitude": float(clicked_point["lng"]),
        }
        if new_pin != existing_pin:
            st.session_state.pinned_location = new_pin
            st.rerun()

    if existing_pin and st.button("Clear selected pin"):
        st.session_state.pop("pinned_location", None)
        st.rerun()


if start_location is None:
    st.info("Select a starting location before Route2Study creates a plan.")
    st.stop()

destination_location = location_lookup[destination_label]
start_snap_distance = nearest_network_distance(walking_graph, start_location)

if start_snap_distance > MAX_NETWORK_SNAP_METERS:
    st.error(
        "This starting point is outside the current Penn-area walking network. "
        "Choose a point closer to campus."
    )
    st.write(
        f"Distance to the nearest network node: {start_snap_distance:.0f} meters"
    )
    st.stop()

if location_accuracy:
    st.caption(
        "Browser-reported location accuracy: "
        f"approximately {float(location_accuracy):.0f} meters."
    )

available_datetime = datetime.combine(date.today(), available_from)
class_start_datetime = datetime.combine(date.today(), class_start_time)
available_minutes = int(
    (class_start_datetime - available_datetime).total_seconds() / 60
)

if available_minutes <= 0:
    st.error("Class must start after the time you become available.")
    st.stop()

recommendations = recommend_study_spaces(
    walking_graph,
    start_location,
    destination_location,
    available_minutes,
    study_preference,
    location_lookup,
    study_location_names,
)

if not recommendations:
    direct_route = calculate_network_route(
        walking_graph, start_location, destination_location
    )

    if direct_route is None:
        st.error("No connected walking route was found.")
        st.stop()

    metric_1, metric_2, metric_3 = st.columns(3)
    metric_1.metric("Time Available", f"{available_minutes} min")
    metric_2.metric(
        "Direct Walking", f"{direct_route['walking_minutes']} min"
    )
    metric_3.metric("Study Recommendation", "Not feasible")
    st.warning(
        "There is not enough time for a study stop of at least "
        f"{MINIMUM_STUDY_MINUTES} minutes."
    )

    direct_map = create_route_map(
        walking_graph,
        start_location,
        start_label,
        destination_location,
        destination_label,
        first_route=direct_route,
    )
    st_folium(
        direct_map,
        width=1100,
        height=500,
        key="direct_route_map",
        returned_objects=[],
    )
    st.stop()

best = recommendations[0]
best_study_location = location_lookup[best["name"]]

metric_1, metric_2, metric_3, metric_4 = st.columns(4)
metric_1.metric("Time Available", f"{available_minutes} min")
metric_2.metric("Total Walking", f"{best['total_walking']} min")
metric_3.metric("Study Time", f"{best['study_minutes']} min")
metric_4.metric("Route Distance", f"{best['total_distance'] / 1000:.1f} km")

safe_study_name = html.escape(best["name"])
st.markdown(
    f"""
    <div class="recommendation-card">
        <h3>Recommended study stop: {safe_study_name}</h3>
        <p>Preference match: {best['preference_match']} / 5</p>
        <p>
            Walk {best['walk_to_study']} minutes to the study space,
            study for approximately {best['study_minutes']} minutes,
            then walk {best['walk_to_class']} minutes to class.
        </p>
    </div>
    """,
    unsafe_allow_html=True,
)

st.subheader("Recommended Route")
route_map = create_route_map(
    walking_graph,
    start_location,
    start_label,
    destination_location,
    destination_label,
    study_location=best_study_location,
    study_label=best["name"],
    first_route=best["route_to_study"],
    second_route=best["route_to_class"],
)
st_folium(
    route_map,
    width=1100,
    height=520,
    key="recommended_route_map",
    returned_objects=[],
)
st.caption(
    "Blue: start to study space. Purple: study space to class. "
    "Routes minimize distance on the OpenStreetMap pedestrian network."
)

st.subheader("Plan Timeline")
timeline_1, timeline_2, timeline_3 = st.columns(3)

with timeline_1:
    st.markdown("**1. Start**")
    st.write(start_label)
    st.write(available_from.strftime("%I:%M %p"))

with timeline_2:
    arrival_time = available_datetime + pd.Timedelta(
        minutes=best["walk_to_study"]
    )
    st.markdown("**2. Study**")
    st.write(best["name"])
    st.write(f"Arrive around {arrival_time.strftime('%I:%M %p')}")

with timeline_3:
    st.markdown("**3. Class**")
    st.write(destination_label)
    st.write(f"Starts at {class_start_time.strftime('%I:%M %p')}")

if len(recommendations) > 1:
    st.subheader("Other Feasible Study Spaces")
    alternatives = pd.DataFrame(recommendations[1:4])[
        [
            "name",
            "total_walking",
            "total_distance",
            "study_minutes",
            "preference_match",
        ]
    ].copy()
    alternatives["total_distance"] = (
        alternatives["total_distance"] / 1000
    ).round(1)
    alternatives = alternatives.rename(
        columns={
            "name": "Study Space",
            "total_walking": "Walking (min)",
            "total_distance": "Distance (km)",
            "study_minutes": "Study Time (min)",
            "preference_match": "Preference Match",
        }
    )
    st.dataframe(alternatives, width="stretch", hide_index=True)

with st.expander("View Location Data"):
    st.dataframe(locations_df, width="stretch", hide_index=True)
