import math
from datetime import date, datetime, time
from pathlib import Path

import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium


st.set_page_config(
    page_title="Route2Study",
    layout="wide",
)


DATA_FILE = Path(__file__).resolve().parent / "data" / "locations.csv"
WALKING_SPEED_MPH = 3.0
ROUTE_DISTANCE_FACTOR = 1.25
TRANSITION_BUFFER_MINUTES = 10
MINIMUM_STUDY_MINUTES = 15

REQUIRED_COLUMNS = {
    "name",
    "latitude",
    "longitude",
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


@st.cache_data
def load_locations(file_path):
    if not file_path.exists():
        raise FileNotFoundError(
            f"Location data was not found at: {file_path}"
        )

    data = pd.read_csv(file_path)
    missing_columns = REQUIRED_COLUMNS - set(data.columns)

    if missing_columns:
        missing = ", ".join(sorted(missing_columns))
        raise ValueError(f"Missing CSV columns: {missing}")

    return data


def haversine_distance(location_1, location_2):
    """Return straight-line distance between two points in miles."""

    earth_radius_miles = 3958.8

    latitude_1 = math.radians(location_1["latitude"])
    longitude_1 = math.radians(location_1["longitude"])
    latitude_2 = math.radians(location_2["latitude"])
    longitude_2 = math.radians(location_2["longitude"])

    latitude_difference = latitude_2 - latitude_1
    longitude_difference = longitude_2 - longitude_1

    a = (
        math.sin(latitude_difference / 2) ** 2
        + math.cos(latitude_1)
        * math.cos(latitude_2)
        * math.sin(longitude_difference / 2) ** 2
    )

    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return earth_radius_miles * c


def estimate_walking_minutes(location_1, location_2):
    """Estimate walking time using distance and a campus-route factor."""

    distance = haversine_distance(location_1, location_2)
    adjusted_distance = distance * ROUTE_DISTANCE_FACTOR
    minutes = (adjusted_distance / WALKING_SPEED_MPH) * 60
    return max(0, round(minutes))


def preference_score(location, preference):
    if preference == "No preference":
        return (
            location["quiet_score"]
            + location["collaborative_score"]
            + location["coffee_score"]
            + location["outlet_score"]
        ) / 4

    score_column = PREFERENCE_COLUMNS[preference]
    return location[score_column]


def recommend_study_spaces(
    start_name,
    destination_name,
    available_minutes,
    preference,
    location_lookup,
    study_location_names,
):
    recommendations = []
    start = location_lookup[start_name]
    destination = location_lookup[destination_name]

    for study_name in study_location_names:
        study_location = location_lookup[study_name]

        walk_to_study = estimate_walking_minutes(
            start,
            study_location,
        )

        walk_to_class = estimate_walking_minutes(
            study_location,
            destination,
        )

        total_walking = walk_to_study + walk_to_class
        study_minutes = (
            available_minutes
            - total_walking
            - TRANSITION_BUFFER_MINUTES
        )

        if study_minutes < MINIMUM_STUDY_MINUTES:
            continue

        preference_match = preference_score(
            study_location,
            preference,
        )

        final_score = (
            study_minutes
            + 15 * preference_match
            + 2 * study_location["outlet_score"]
            - 0.5 * total_walking
        )

        recommendations.append(
            {
                "name": study_name,
                "walk_to_study": walk_to_study,
                "walk_to_class": walk_to_class,
                "total_walking": total_walking,
                "study_minutes": study_minutes,
                "preference_match": round(preference_match, 1),
                "final_score": round(final_score, 1),
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


def create_route_map(
    start_name,
    destination_name,
    location_lookup,
    study_name=None,
):
    start = location_lookup[start_name]
    destination = location_lookup[destination_name]

    campus_map = folium.Map(
        location=[39.9522, -75.1930],
        zoom_start=16,
        tiles="OpenStreetMap",
    )

    add_marker(
        campus_map,
        start,
        start_name,
        "green",
        "First class",
    )

    add_marker(
        campus_map,
        destination,
        destination_name,
        "red",
        "Next class",
    )

    route_points = [
        [start["latitude"], start["longitude"]],
    ]

    if study_name:
        study_location = location_lookup[study_name]
        add_marker(
            campus_map,
            study_location,
            study_name,
            "blue",
            "Recommended study location",
        )
        route_points.append(
            [
                study_location["latitude"],
                study_location["longitude"],
            ]
        )

    route_points.append(
        [destination["latitude"], destination["longitude"]]
    )

    folium.PolyLine(
        locations=route_points,
        color="#4F46E5",
        weight=6,
        opacity=0.85,
        dash_array="10",
        tooltip="Prototype route",
    ).add_to(campus_map)

    campus_map.fit_bounds(route_points, padding=(40, 40))
    return campus_map


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
            background: linear-gradient(
                120deg,
                #4338CA,
                #2563EB,
                #0891B2
            );
            margin-bottom: 25px;
            box-shadow: 0 10px 30px rgba(37, 99, 235, 0.18);
        }

        .hero h1 {
            margin: 0;
            font-size: 44px;
        }

        .hero p {
            margin: 8px 0 0 0;
            font-size: 18px;
        }

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

        .recommendation-card p {
            margin: 4px 0;
            color: #1F2937;
        }
    </style>

    <div class="hero">
        <h1>Route2Study</h1>
        <p>
            Turn the time between classes into productive study time.
        </p>
    </div>
    """,
    unsafe_allow_html=True,
)


try:
    locations_df = load_locations(DATA_FILE)
except (FileNotFoundError, ValueError) as error:
    st.error(str(error))
    st.info(
        "Confirm that data/locations.csv exists and contains "
        "all required columns."
    )
    st.stop()


location_lookup = (
    locations_df.set_index("name").to_dict(orient="index")
)

class_location_names = locations_df.loc[
    locations_df["can_be_class"] == 1,
    "name",
].tolist()

study_location_names = locations_df.loc[
    locations_df["can_be_study"] == 1,
    "name",
].tolist()


with st.sidebar:
    st.header("Plan Your Day")

    first_location = st.selectbox(
        "First class",
        class_location_names,
    )

    first_class_end = st.time_input(
        "First class ends",
        value=time(11, 30),
    )

    next_location = st.selectbox(
        "Next class",
        class_location_names,
        index=min(1, len(class_location_names) - 1),
    )

    next_class_start = st.time_input(
        "Next class starts",
        value=time(14, 0),
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
    )

    st.caption(
        "Walking times are prototype estimates and do not yet "
        "follow the street network."
    )


first_end_datetime = datetime.combine(
    date.today(),
    first_class_end,
)

next_start_datetime = datetime.combine(
    date.today(),
    next_class_start,
)

available_minutes = int(
    (
        next_start_datetime - first_end_datetime
    ).total_seconds()
    / 60
)


if available_minutes <= 0:
    st.error(
        "The next class must start after the first class ends."
    )
    st.stop()

if first_location == next_location:
    st.warning(
        "The two classes are in the same building. "
        "Route2Study will still search for a useful study stop."
    )


recommendations = recommend_study_spaces(
    first_location,
    next_location,
    available_minutes,
    study_preference,
    location_lookup,
    study_location_names,
)


if not recommendations:
    direct_walking = estimate_walking_minutes(
        location_lookup[first_location],
        location_lookup[next_location],
    )

    metric_1, metric_2, metric_3 = st.columns(3)
    metric_1.metric("Time Between Classes", f"{available_minutes} min")
    metric_2.metric("Direct Walking", f"{direct_walking} min")
    metric_3.metric("Study Recommendation", "Not feasible")

    st.warning(
        "There is not enough time for a study stop of at least "
        f"{MINIMUM_STUDY_MINUTES} minutes."
    )

    direct_map = create_route_map(
        first_location,
        next_location,
        location_lookup,
    )

    st_folium(
        direct_map,
        width=1100,
        height=500,
        returned_objects=[],
    )
    st.stop()


best = recommendations[0]

metric_1, metric_2, metric_3 = st.columns(3)
metric_1.metric("Time Between Classes", f"{available_minutes} min")
metric_2.metric("Total Walking", f"{best['total_walking']} min")
metric_3.metric("Available Study Time", f"{best['study_minutes']} min")


st.markdown(
    f"""
    <div class="recommendation-card">
        <h3>Recommended study stop: {best['name']}</h3>
        <p>
            Preference match: {best['preference_match']} / 5
        </p>
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
    first_location,
    next_location,
    location_lookup,
    study_name=best["name"],
)

st_folium(
    route_map,
    width=1100,
    height=500,
    returned_objects=[],
)

st.caption(
    "The dashed segments are prototype route estimates. "
    "Street-level shortest paths will be added in a later version."
)


st.subheader("Plan Timeline")

timeline_1, timeline_2, timeline_3 = st.columns(3)

with timeline_1:
    st.markdown("**1. Leave class**")
    st.write(first_location)
    st.write(first_class_end.strftime("%I:%M %p"))

with timeline_2:
    arrival_time = (
        first_end_datetime
        + pd.Timedelta(minutes=best["walk_to_study"])
    )
    st.markdown("**2. Study**")
    st.write(best["name"])
    st.write(
        f"Arrive around {arrival_time.strftime('%I:%M %p')}"
    )

with timeline_3:
    st.markdown("**3. Next class**")
    st.write(next_location)
    st.write(f"Starts at {next_class_start.strftime('%I:%M %p')}")


if len(recommendations) > 1:
    st.subheader("Other Feasible Study Spaces")

    alternatives = pd.DataFrame(recommendations[1:4])[
        [
            "name",
            "total_walking",
            "study_minutes",
            "preference_match",
        ]
    ].rename(
        columns={
            "name": "Study Space",
            "total_walking": "Walking (min)",
            "study_minutes": "Study Time (min)",
            "preference_match": "Preference Match",
        }
    )

    st.dataframe(
        alternatives,
        use_container_width=True,
        hide_index=True,
    )


with st.expander("View Location Data"):
    st.dataframe(
        locations_df,
        use_container_width=True,
        hide_index=True,
    )