import html
import json
import math
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

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

from personalization import (
    DEFAULT_PROFILE,
    WALKING_PACES,
    build_calendar_ics,
    build_google_maps_directions_url,
    build_plan_summary,
    normalize_profile,
    walking_speed_for_pace,
)
from research.reporting import (
    load_raw_rigorous_summary,
    load_saved_summary,
)
from venue_status import (
    PENN_LIBRARY_HOURS_URL,
    CrowdReportStore,
    crowd_penalty,
    september_2026_regular_hours,
    fetch_penn_library_hours,
    is_open_at,
)


st.set_page_config(page_title="Route2Study", page_icon="🗺️", layout="wide")

PROJECT_ROOT = Path(__file__).resolve().parent
DATA_FILE = PROJECT_ROOT / "data" / "penn_locations.csv"
NETWORK_FILE = PROJECT_ROOT / "data" / "penn_walking_network.graphml"
RESULTS_DIR = PROJECT_ROOT / "research" / "results"

CAMPUS_CENTER = (39.9522, -75.1930)
WALKING_SPEED_METERS_PER_MINUTE = 80
TRANSITION_BUFFER_MINUTES = 10
MINIMUM_STUDY_MINUTES = 15
MAX_NETWORK_SNAP_METERS = 500
PENN_TIMEZONE = ZoneInfo("America/New_York")

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
    metadata = None

    try:
        if result_kind == "raw":
            summary = load_raw_rigorous_summary(result_path)
            metadata_path = result_path.with_suffix(".metadata.json")
            if metadata_path.exists():
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
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

    operational_available = {
        "study_plan_rate_percent",
        "mean_deadline_slack_minutes",
        "mean_walking_detour_minutes",
    }.issubset(summary.columns)
    if operational_available:
        exact = exact_rows.iloc[0] if not exact_rows.empty else summary.iloc[0]
        outcome_1, outcome_2, outcome_3 = st.columns(3)
        outcome_1.metric(
            "Exact study-plan rate",
            f"{exact['study_plan_rate_percent']:.1f}%",
        )
        outcome_2.metric(
            "Exact mean slack",
            f"{exact['mean_deadline_slack_minutes']:.1f} min",
        )
        detour_value = exact["mean_walking_detour_minutes"]
        outcome_3.metric(
            "Exact mean detour",
            f"{detour_value:.1f} min" if pd.notna(detour_value) else "Pending rerun",
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
        if operational_available:
            st.subheader("Study-plan Rate (%)")
            st.bar_chart(chart_data[["study_plan_rate_percent"]])
        else:
            st.subheader("Mean Runtime (ms)")
            st.bar_chart(chart_data[["mean_runtime_ms"]])

    if operational_available:
        chart_left, chart_right = st.columns(2)
        with chart_left:
            st.subheader("Mean Deadline Slack (min)")
            st.bar_chart(chart_data[["mean_deadline_slack_minutes"]])
        with chart_right:
            st.subheader("Mean Walking Detour (min)")
            if summary["mean_walking_detour_minutes"].notna().any():
                st.bar_chart(chart_data[["mean_walking_detour_minutes"]])
            else:
                st.info(
                    "Walking detour needs `direct_travel_minutes`. Run the "
                    "updated Penn benchmark to populate it."
                )

        st.subheader("Mean Solver Runtime (ms)")
        st.bar_chart(chart_data[["mean_runtime_ms"]])

    display_columns = [
        "method",
        "scenarios",
        "mean_reward",
        "mean_gap_percent",
        "feasible_rate_percent",
    ]
    display_names = [
        "Method",
        "Scenarios",
        "Mean reward",
        "Gap (%)",
        "Feasible (%)",
    ]
    if operational_available:
        display_columns.extend(
            [
                "study_plan_rate_percent",
                "mean_deadline_slack_minutes",
                "mean_walking_detour_minutes",
            ]
        )
        display_names.extend(
            ["Study plan (%)", "Slack (min)", "Detour (min)"]
        )
    display_columns.append("mean_runtime_ms")
    display_names.append("Runtime (ms)")
    display = summary[display_columns].copy()
    display.columns = display_names
    for column in display.columns[2:]:
        display[column] = display[column].round(3)

    st.subheader("Summary Table")
    st.dataframe(display, width="stretch", hide_index=True)
    if {
        "reward_std",
        "reward_ci_low",
        "reward_ci_high",
        "median_runtime_ms",
        "p95_runtime_ms",
    }.issubset(summary.columns):
        rigorous = summary[
            [
                "method",
                "reward_std",
                "reward_ci_low",
                "reward_ci_high",
                "gap_ci_low",
                "gap_ci_high",
                "study_plan_ci_low",
                "study_plan_ci_high",
                "slack_ci_low",
                "slack_ci_high",
                "median_runtime_ms",
                "p95_runtime_ms",
            ]
        ].copy()
        rigorous.columns = [
            "Method",
            "Reward SD",
            "Reward CI low",
            "Reward CI high",
            "Gap CI low",
            "Gap CI high",
            "Study-plan CI low",
            "Study-plan CI high",
            "Slack CI low",
            "Slack CI high",
            "Median runtime (ms)",
            "P95 runtime (ms)",
        ]
        numeric_columns = rigorous.columns[1:]
        rigorous[numeric_columns] = rigorous[numeric_columns].round(3)
        st.subheader("Uncertainty and Runtime Distribution")
        st.dataframe(rigorous, width="stretch", hide_index=True)
        st.caption(
            "Intervals are reproducible 95% bootstrap confidence intervals "
            "(2,000 resamples; seed 2026). Runtime median and P95 are shown "
            "because very short wall-clock measurements are often skewed."
        )
    if metadata:
        st.subheader("Experiment Protocol")
        protocol_1, protocol_2, protocol_3, protocol_4 = st.columns(4)
        protocol_1.metric("Warm-up runs", metadata.get("warmup_runs", "—"))
        protocol_2.metric(
            "Timing repeats", metadata.get("timing_repeats", "—")
        )
        protocol_3.metric(
            "Preprocessing",
            f"{metadata.get('preprocessing_ms', 0):.1f} ms",
        )
        protocol_4.metric("Order seed", metadata.get("order_seed", "—"))
        st.caption(
            "Preprocessing is reported separately and is not included in solver runtime. "
            f"Travel matrix source: {metadata.get('matrix_source', 'unknown')}."
        )
    st.info(
        "Feasible means the route reaches class within budget; study-plan rate "
        "separately measures whether at least one study stop was scheduled. "
        "The Penn preference scores are prototype engineering values, not "
        "survey-validated student ratings. Treat these results as an "
        "algorithm benchmark rather than a user-behavior claim."
    )


@st.cache_data(ttl=900, show_spinner=False)
def load_official_hours(planning_moment):
    """Load today's Penn Libraries hours with a short-lived cache."""

    try:
        hours = fetch_penn_library_hours()
        if not hours:
            raise ValueError("Penn hours page returned no supported locations")
        return hours, "live", None
    except (OSError, TimeoutError, ValueError) as error:
        return september_2026_regular_hours(planning_moment), "month_schedule", str(error)


@st.cache_resource
def get_crowd_store():
    return CrowdReportStore(retention_hours=2)


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


def calculate_network_route(
    graph,
    location_1,
    location_2,
    walking_speed_meters_per_minute=WALKING_SPEED_METERS_PER_MINUTE,
):
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
        distance_meters / walking_speed_meters_per_minute
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
    planned_start_datetime,
    venue_hours,
    crowd_store,
    walking_speed_meters_per_minute=WALKING_SPEED_METERS_PER_MINUTE,
    transition_buffer_minutes=TRANSITION_BUFFER_MINUTES,
    minimum_study_minutes=MINIMUM_STUDY_MINUTES,
    favorite_study_spaces=None,
    crowd_aware=True,
    require_verified_open=False,
):
    recommendations = []
    favorite_study_spaces = set(favorite_study_spaces or [])

    for study_name in study_location_names:
        study_location = location_lookup[study_name]
        route_to_study = calculate_network_route(
            graph,
            start_location,
            study_location,
            walking_speed_meters_per_minute,
        )
        route_to_class = calculate_network_route(
            graph,
            study_location,
            destination_location,
            walking_speed_meters_per_minute,
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
            available_minutes - total_walking - transition_buffer_minutes
        )

        if study_minutes < minimum_study_minutes:
            continue

        arrival_datetime = planned_start_datetime + pd.Timedelta(
            minutes=walk_to_study
        )
        hours_text = venue_hours.get(study_name)
        open_status = is_open_at(hours_text, arrival_datetime)
        crowd = crowd_store.summarize(study_name)
        if open_status is False:
            continue
        if require_verified_open and open_status is not True:
            continue
        if crowd_aware and crowd.level == "Full":
            continue

        match_score = preference_score(study_location, preference)
        favorite_bonus = 12 if study_name in favorite_study_spaces else 0
        final_score = (
            study_minutes
            + 15 * match_score
            + 2 * study_location["outlet_score"]
            - 0.5 * total_walking
            - (crowd_penalty(crowd.level) if crowd_aware else 0)
            + favorite_bonus
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
                "hours": hours_text or "Not published in the live library feed",
                "open_status": open_status,
                "crowd_level": crowd.level,
                "crowd_reports": crowd.reports,
                "crowd_updated": crowd.latest_at,
                "is_favorite": study_name in favorite_study_spaces,
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


def apply_profile_to_planner(profile):
    """Copy saved routine values into the interactive planner widgets."""

    st.session_state["planner_start_mode"] = "Campus building"
    st.session_state["planner_start_building"] = profile["default_start"]
    st.session_state["planner_destination"] = profile["default_destination"]
    st.session_state["planner_preference"] = profile["study_preference"]


def initialize_planner_widgets(profile):
    st.session_state.setdefault("planner_start_mode", "Campus building")
    st.session_state.setdefault(
        "planner_start_building", profile["default_start"]
    )
    st.session_state.setdefault(
        "planner_destination", profile["default_destination"]
    )
    st.session_state.setdefault(
        "planner_preference", profile["study_preference"]
    )
    st.session_state.setdefault("planner_available_from", time(11, 30))
    st.session_state.setdefault("planner_class_start", time(14, 0))


def render_profile_editor(
    profile,
    start_location_names,
    class_location_names,
    study_location_names,
):
    """Render a session-level routine editor and return the saved profile."""

    st.header("My Routine")
    st.write(
        "Set the defaults Route2Study should use when you are in a hurry. "
        "Your routine stays in this browser session and never needs an account."
    )

    with st.form("profile_form"):
        identity_col, pace_col = st.columns(2)
        with identity_col:
            display_name = st.text_input(
                "First name or nickname",
                value=profile["display_name"],
                placeholder="How should Route2Study greet you?",
            )
            default_start = st.selectbox(
                "Usual starting point",
                start_location_names,
                index=start_location_names.index(profile["default_start"]),
            )
            default_destination = st.selectbox(
                "Usual class building",
                class_location_names,
                index=class_location_names.index(
                    profile["default_destination"]
                ),
            )
        with pace_col:
            study_preference = st.selectbox(
                "What matters most in a study space?",
                [
                    "Quiet",
                    "Collaborative",
                    "Coffee nearby",
                    "Power outlets",
                    "No preference",
                ],
                index=[
                    "Quiet",
                    "Collaborative",
                    "Coffee nearby",
                    "Power outlets",
                    "No preference",
                ].index(profile["study_preference"]),
            )
            walking_pace = st.segmented_control(
                "Walking pace",
                list(WALKING_PACES),
                default=profile["walking_pace"],
            )
            favorite_spaces = st.multiselect(
                "Favorite study spaces (up to 5)",
                study_location_names,
                default=profile["favorite_spaces"],
                max_selections=5,
            )

        rule_col, filter_col = st.columns(2)
        with rule_col:
            minimum_study_minutes = st.slider(
                "Minimum worthwhile study block",
                min_value=10,
                max_value=60,
                value=profile["minimum_study_minutes"],
                step=5,
                format="%d min",
            )
            transition_buffer_minutes = st.slider(
                "Transition buffer before class",
                min_value=0,
                max_value=25,
                value=profile["transition_buffer_minutes"],
                step=5,
                format="%d min",
            )
        with filter_col:
            crowd_aware = st.toggle(
                "Use live crowd reports",
                value=profile["crowd_aware"],
                help="Avoid spaces reported as full and account for busy rooms.",
            )
            require_verified_open = st.toggle(
                "Only recommend verified-open spaces",
                value=profile["require_verified_open"],
                help=(
                    "Stricter, but may hide useful academic buildings whose "
                    "hours are not published in the Penn Libraries feed."
                ),
            )

        saved = st.form_submit_button(
            "Save my routine", type="primary", width="stretch"
        )

    if saved:
        profile = normalize_profile(
            {
                "display_name": display_name,
                "default_start": default_start,
                "default_destination": default_destination,
                "study_preference": study_preference,
                "walking_pace": walking_pace or "Standard",
                "minimum_study_minutes": minimum_study_minutes,
                "transition_buffer_minutes": transition_buffer_minutes,
                "favorite_spaces": favorite_spaces,
                "crowd_aware": crowd_aware,
                "require_verified_open": require_verified_open,
            },
            valid_starts=start_location_names,
            valid_destinations=class_location_names,
            valid_study_spaces=study_location_names,
        )
        st.session_state.user_profile = profile
        apply_profile_to_planner(profile)
        st.success("Routine saved. Your next plan can use it in one tap.")

    st.markdown(
        f"""
        <div class="routine-summary">
            <div><span>Home base</span><strong>{html.escape(profile['default_start'])}</strong></div>
            <div><span>Default class</span><strong>{html.escape(profile['default_destination'])}</strong></div>
            <div><span>Study style</span><strong>{html.escape(profile['study_preference'])}</strong></div>
            <div><span>Walking pace</span><strong>{html.escape(profile['walking_pace'])}</strong></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if st.button("Reset routine to defaults", width="stretch"):
        reset_profile = normalize_profile(
            DEFAULT_PROFILE,
            valid_starts=start_location_names,
            valid_destinations=class_location_names,
            valid_study_spaces=study_location_names,
        )
        st.session_state.user_profile = reset_profile
        apply_profile_to_planner(reset_profile)
        st.rerun()

    st.caption(
        "This version stores preferences only in the active Streamlit session. "
        "Persistent accounts can be added later without changing the planner API."
    )
    return profile


if "user_profile" not in st.session_state:
    st.session_state.user_profile = DEFAULT_PROFILE.copy()
    st.session_state.user_profile["favorite_spaces"] = []

profile_preview = st.session_state.user_profile
safe_name = html.escape(str(profile_preview.get("display_name", "")).strip())
local_hour = datetime.now(PENN_TIMEZONE).hour
daypart = (
    "Good morning"
    if local_hour < 12
    else "Good afternoon" if local_hour < 18 else "Good evening"
)
hero_title = f"{daypart}, {safe_name}" if safe_name else "Make the gap count"


st.markdown(
    """
    <style>
        .stApp {
            background:
                radial-gradient(circle at 8% 4%, rgba(99, 102, 241, 0.10), transparent 26rem),
                radial-gradient(circle at 92% 20%, rgba(6, 182, 212, 0.08), transparent 24rem),
                #F8FAFC;
        }
        .block-container {
            max-width: 1280px;
            padding-top: 2rem;
            padding-bottom: 3rem;
        }
        .hero {
            position: relative;
            overflow: hidden;
            padding: 34px;
            border-radius: 26px;
            color: white;
            background: linear-gradient(125deg, #312E81 0%, #2563EB 52%, #06B6D4 115%);
            margin-bottom: 25px;
            box-shadow: 0 22px 55px rgba(37, 99, 235, 0.22);
        }
        .hero::after {
            content: "";
            position: absolute;
            width: 240px;
            height: 240px;
            right: -70px;
            top: -90px;
            border-radius: 999px;
            background: rgba(255, 255, 255, 0.12);
        }
        .hero-brand {
            margin: 0 0 18px 0;
            font-size: 13px;
            letter-spacing: 0.14em;
            text-transform: uppercase;
            font-weight: 700;
            opacity: 0.82;
        }
        .hero h1 { margin: 0; font-size: 44px; letter-spacing: -0.035em; }
        .hero p { margin: 9px 0 0 0; font-size: 18px; max-width: 650px; }
        div[data-testid="stSegmentedControl"] {
            position: sticky;
            top: 0.6rem;
            z-index: 10;
            padding: 7px;
            border: 1px solid rgba(148, 163, 184, 0.30);
            border-radius: 16px;
            background: rgba(248, 250, 252, 0.90);
            backdrop-filter: blur(14px);
        }
        .recommendation-card {
            padding: 22px;
            border: 1px solid rgba(37, 99, 235, 0.20);
            border-left: 7px solid #2563EB;
            border-radius: 18px;
            background: linear-gradient(135deg, #EFF6FF, #ECFEFF);
            margin: 12px 0 22px 0;
            box-shadow: 0 12px 30px rgba(15, 23, 42, 0.07);
        }
        .recommendation-card h3 {
            margin: 0 0 8px 0;
            color: #1E3A8A;
        }
        .recommendation-card p { margin: 4px 0; color: #1F2937; }
        .status-pill {
            display: inline-block;
            padding: 3px 9px;
            border-radius: 999px;
            margin: 3px 6px 3px 0;
            background: rgba(255, 255, 255, 0.75);
            color: #1E3A8A;
            font-size: 14px;
            font-weight: 600;
        }
        .reason-pill {
            display: inline-block;
            padding: 6px 10px;
            border-radius: 999px;
            margin: 7px 6px 0 0;
            background: #FFFFFF;
            color: #334155;
            font-size: 13px;
            border: 1px solid rgba(148, 163, 184, 0.28);
        }
        .routine-summary {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 12px;
            margin: 20px 0;
        }
        .routine-summary div {
            padding: 16px;
            border-radius: 16px;
            background: white;
            border: 1px solid #E2E8F0;
            box-shadow: 0 8px 24px rgba(15, 23, 42, 0.05);
        }
        .routine-summary span {
            display: block;
            color: #64748B;
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 0.06em;
            margin-bottom: 5px;
        }
        .routine-summary strong { color: #0F172A; font-size: 15px; }
        .time-bar {
            display: flex;
            height: 12px;
            overflow: hidden;
            border-radius: 999px;
            background: #E2E8F0;
            margin: 12px 0 7px 0;
        }
        .time-bar-walk { background: #2563EB; }
        .time-bar-study { background: #14B8A6; }
        .time-bar-buffer { background: #A78BFA; }
        @media (max-width: 700px) {
            .block-container {
                padding: 0.75rem 0.75rem 2rem 0.75rem;
            }
            .hero {
                padding: 20px 18px;
                border-radius: 16px;
                margin-bottom: 14px;
            }
            .hero h1 { font-size: 32px; }
            .hero p { font-size: 15px; line-height: 1.45; }
            .recommendation-card { padding: 16px; }
            .routine-summary { grid-template-columns: repeat(2, minmax(0, 1fr)); }
            div[data-testid="stMetric"] {
                border: 1px solid rgba(49, 51, 63, 0.12);
                border-radius: 12px;
                padding: 10px;
            }
        }
    </style>
    <div class="hero">
        <div class="hero-brand">Route2Study · Penn campus planner</div>
        <h1>__HERO_TITLE__</h1>
        <p>Turn the time before class into a study plan that fits your route, pace, and preferences.</p>
    </div>
    """.replace("__HERO_TITLE__", hero_title),
    unsafe_allow_html=True,
)

app_view = st.segmented_control(
    "Route2Study view",
    ["Plan", "My routine", "Research"],
    default="Plan",
    key="app_view",
    label_visibility="collapsed",
)

if app_view == "Research":
    render_research_benchmark()
    st.stop()


try:
    locations_df = load_locations(DATA_FILE)
except (FileNotFoundError, ValueError) as error:
    st.error(str(error))
    st.info("Confirm that data/penn_locations.csv exists.")
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

user_profile = normalize_profile(
    st.session_state.user_profile,
    valid_starts=start_location_names,
    valid_destinations=class_location_names,
    valid_study_spaces=study_location_names,
)
st.session_state.user_profile = user_profile

if app_view == "My routine":
    render_profile_editor(
        user_profile,
        start_location_names,
        class_location_names,
        study_location_names,
    )
    st.stop()

try:
    walking_graph = load_walking_network(NETWORK_FILE)
except FileNotFoundError as error:
    st.error(str(error))
    st.info("Confirm that data/penn_walking_network.graphml exists.")
    st.stop()

initialize_planner_widgets(user_profile)

st.subheader("Plan your next gap")
st.caption(
    f"Using a {user_profile['walking_pace'].lower()} walking pace, "
    f"a {user_profile['transition_buffer_minutes']}-minute class buffer, "
    f"and at least {user_profile['minimum_study_minutes']} minutes to study."
)
quick_1, quick_2 = st.columns(2)
with quick_1:
    if st.button(
        "Use my routine",
        type="primary",
        width="stretch",
        help="Load your usual start, class building, and study preference.",
    ):
        apply_profile_to_planner(user_profile)
        st.rerun()
with quick_2:
    if st.button(
        "Start from now · class in 90 min",
        width="stretch",
        help="Create a quick plan using the current Penn time.",
    ):
        now = datetime.now(PENN_TIMEZONE)
        rounded_minute = ((now.minute + 4) // 5) * 5
        if rounded_minute >= 60:
            rounded_now = now.replace(minute=0, second=0, microsecond=0)
            rounded_now += pd.Timedelta(hours=1)
        else:
            rounded_now = now.replace(
                minute=rounded_minute, second=0, microsecond=0
            )
        class_datetime = rounded_now + pd.Timedelta(minutes=90)
        st.session_state["planner_available_from"] = rounded_now.time()
        st.session_state["planner_class_start"] = class_datetime.time()
        st.rerun()

start_location = None
start_label = None
location_accuracy = None


with st.expander("Plan settings", expanded=True):
    st.header("Plan Your Day")
    start_mode = st.selectbox(
        "Starting point method",
        [
            "Campus building",
            "Street address",
            "Drop a pin",
            "Current location",
        ],
        key="planner_start_mode",
    )

    if start_mode == "Campus building":
        start_label = st.selectbox(
            "Starting building or residence",
            start_location_names,
            key="planner_start_building",
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

    available_from = st.time_input(
        "Available from", key="planner_available_from"
    )
    destination_label = st.selectbox(
        "Destination class",
        class_location_names,
        key="planner_destination",
        format_func=lambda name: f"{name} · Academic",
    )
    class_start_time = st.time_input(
        "Class starts", key="planner_class_start"
    )
    study_preference = st.selectbox(
        "Study preference",
        [
            "Quiet",
            "Collaborative",
            "Coffee nearby",
            "Power outlets",
            "No preference",
        ],
        key="planner_preference",
    )

    st.divider()
    st.markdown("**Share a live crowd report**")
    crowd_store = get_crowd_store()
    with st.form("crowd_report_form", border=False):
        report_venue = st.selectbox("Study space", study_location_names)
        report_level = st.segmented_control(
            "How crowded is it?",
            list(CrowdReportStore.LEVELS),
            default="Moderate",
        )
        report_submitted = st.form_submit_button(
            "Submit anonymous report", width="stretch"
        )
    if report_submitted and report_level:
        crowd_store.add(report_venue, report_level)
        st.success(
            f"Live report added for {report_venue}. It will expire in 2 hours."
        )
    st.caption(
        "Crowd reports are anonymous, shared with current app users, and "
        "automatically expire after two hours. They reset if the app restarts."
    )


if start_mode == "Drop a pin":
    st.subheader("Choose Your Starting Point")
    st.write("Click anywhere on the map to place the starting pin.")
    existing_pin = st.session_state.get("pinned_location")
    picker_map = create_pin_picker(existing_pin)
    picker_result = st_folium(
        picker_map,
        height=390,
        key="start_location_picker",
        returned_objects=["last_clicked"],
        use_container_width=True,
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

planning_date = datetime.now(PENN_TIMEZONE).date()
available_datetime = datetime.combine(
    planning_date, available_from, tzinfo=PENN_TIMEZONE
)
class_start_datetime = datetime.combine(
    planning_date, class_start_time, tzinfo=PENN_TIMEZONE
)
available_minutes = int(
    (class_start_datetime - available_datetime).total_seconds() / 60
)

if available_minutes <= 0:
    st.error("Class must start after the time you become available.")
    st.stop()

official_hours, hours_source, hours_error = load_official_hours(available_datetime)
if hours_source == "month_schedule" and official_hours:
    st.caption(
        "Live Penn hours could not be refreshed, so this plan uses the official "
        "September 2026 regular schedule verified September 14. Check the source for "
        "holiday or event exceptions."
    )
elif not official_hours:
    st.caption(
        "Penn Libraries' live hours could not be refreshed. Opening status is "
        "left unknown; use the official source link below before traveling."
    )

recommendations = recommend_study_spaces(
    walking_graph,
    start_location,
    destination_location,
    available_minutes,
    study_preference,
    location_lookup,
    study_location_names,
    available_datetime,
    official_hours,
    crowd_store,
    walking_speed_meters_per_minute=walking_speed_for_pace(
        user_profile["walking_pace"]
    ),
    transition_buffer_minutes=user_profile["transition_buffer_minutes"],
    minimum_study_minutes=user_profile["minimum_study_minutes"],
    favorite_study_spaces=user_profile["favorite_spaces"],
    crowd_aware=user_profile["crowd_aware"],
    require_verified_open=user_profile["require_verified_open"],
)

if not recommendations:
    direct_route = calculate_network_route(
        walking_graph,
        start_location,
        destination_location,
        walking_speed_for_pace(user_profile["walking_pace"]),
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
        "No study space satisfies the current time budget and routine filters. "
        f"The planner requires at least {user_profile['minimum_study_minutes']} "
        "minutes of study time; try relaxing the opening-hours filter, choosing "
        "a shorter minimum block, or leaving earlier."
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
        height=500,
        key="direct_route_map",
        returned_objects=[],
        use_container_width=True,
    )
    st.stop()

best = recommendations[0]
best_study_location = location_lookup[best["name"]]
arrival_time = available_datetime + pd.Timedelta(
    minutes=best["walk_to_study"]
)
study_end_time = arrival_time + pd.Timedelta(minutes=best["study_minutes"])

metric_1, metric_2, metric_3, metric_4 = st.columns(4)
metric_1.metric("Time Available", f"{available_minutes} min")
metric_2.metric("Total Walking", f"{best['total_walking']} min")
metric_3.metric("Study Time", f"{best['study_minutes']} min")
metric_4.metric("Route Distance", f"{best['total_distance'] / 1000:.1f} km")

safe_study_name = html.escape(best["name"])
safe_hours = html.escape(best["hours"])
open_label = "Open at arrival" if best["open_status"] is True else "Hours unverified"
crowd_label = html.escape(best["crowd_level"])
crowd_detail = (
    f"{best['crowd_reports']} report(s) in the last 2 hours"
    if best["crowd_reports"]
    else "No recent reports"
)
personal_reasons = [f"{best['study_minutes']} min of focused study time"]
if best["is_favorite"]:
    personal_reasons.insert(0, "One of your saved favorites")
if best["open_status"] is True:
    personal_reasons.append("Verified open when you arrive")
if user_profile["crowd_aware"] and best["crowd_level"] != "Unknown":
    personal_reasons.append(f"Crowding is {best['crowd_level'].lower()}")
if study_preference != "No preference":
    personal_reasons.append(
        f"{best['preference_match']} / 5 match for {study_preference.lower()}"
    )
reason_html = "".join(
    f'<span class="reason-pill">{html.escape(reason)}</span>'
    for reason in personal_reasons
)
favorite_badge = (
    '<span class="status-pill">★ Saved favorite</span>'
    if best["is_favorite"]
    else ""
)
st.markdown(
    f"""
    <div class="recommendation-card">
        <h3>Recommended study stop: {safe_study_name}</h3>
        <span class="status-pill">{open_label} · {safe_hours}</span>
        <span class="status-pill">Crowding: {crowd_label} · {crowd_detail}</span>
        {favorite_badge}
        <p>
            Walk {best['walk_to_study']} minutes to the study space,
            study for approximately {best['study_minutes']} minutes,
            then walk {best['walk_to_class']} minutes to class.
        </p>
        <div>{reason_html}</div>
    </div>
    """,
    unsafe_allow_html=True,
)

walk_share = min(100, 100 * best["total_walking"] / available_minutes)
study_share = min(100 - walk_share, 100 * best["study_minutes"] / available_minutes)
buffer_share = max(0, 100 - walk_share - study_share)
st.markdown(
    f"""
    <div class="time-bar" aria-label="Time allocation">
        <div class="time-bar-walk" style="width:{walk_share:.1f}%"></div>
        <div class="time-bar-study" style="width:{study_share:.1f}%"></div>
        <div class="time-bar-buffer" style="width:{buffer_share:.1f}%"></div>
    </div>
    """,
    unsafe_allow_html=True,
)
st.caption(
    "Time allocation · 🔵 walking  ·  🟢 studying  ·  🟣 transition buffer"
)

plan_summary = build_plan_summary(
    start_label=start_label,
    study_label=best["name"],
    destination_label=destination_label,
    start_datetime=available_datetime,
    arrival_datetime=arrival_time,
    class_datetime=class_start_datetime,
    study_minutes=best["study_minutes"],
    total_walking_minutes=best["total_walking"],
)
calendar_file = build_calendar_ics(
    start_datetime=arrival_time,
    end_datetime=study_end_time,
    study_label=best["name"],
    destination_label=destination_label,
    description=plan_summary,
)
directions_url = build_google_maps_directions_url(
    start_location,
    best_study_location,
    destination_location,
)
action_1, action_2, action_3 = st.columns(3)
with action_1:
    st.link_button(
        "Open walking directions",
        directions_url,
        width="stretch",
    )
with action_2:
    st.download_button(
        "Add study block to calendar",
        data=calendar_file,
        file_name="route2study-plan.ics",
        mime="text/calendar",
        width="stretch",
    )
with action_3:
    st.download_button(
        "Save plan summary",
        data=plan_summary,
        file_name="route2study-plan.txt",
        mime="text/plain",
        width="stretch",
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
    height=520,
    key="recommended_route_map",
    returned_objects=[],
    use_container_width=True,
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
            "hours",
            "crowd_level",
            "crowd_reports",
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
            "hours": "Today's Hours",
            "crowd_level": "Crowding",
            "crowd_reports": "Live Reports",
        }
    )
    st.dataframe(alternatives, width="stretch", hide_index=True)

st.subheader("Live Venue Status")
status_rows = []
for venue_name in study_location_names:
    crowd = crowd_store.summarize(venue_name)
    status_rows.append(
        {
            "Study Space": venue_name,
            "Today's Official Hours": official_hours.get(
                venue_name, "Not available from Penn Libraries"
            ),
            "Crowding": crowd.level,
            "Reports (last 2h)": crowd.reports,
            "Last Report": (
                crowd.latest_at.strftime("%I:%M %p") if crowd.latest_at else "—"
            ),
        }
    )
st.dataframe(pd.DataFrame(status_rows), width="stretch", hide_index=True)
st.caption(
    f"Library hours: [Penn Libraries official Hours page]({PENN_LIBRARY_HOURS_URL}), "
    "cached for 15 minutes. When live refresh is unavailable during September, "
    "the verified September 2026 schedule is used; academic-building hours are not inferred."
)

with st.expander("View Location Data"):
    st.dataframe(locations_df, width="stretch", hide_index=True)
