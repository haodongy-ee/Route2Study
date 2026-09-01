# Route2Study

Route2Study is a campus route and study-space planner that helps students turn the time between classes into productive study time.

## Motivation

Students often have limited time between classes and may not know which nearby study space best fits their schedule and preferences. Route2Study recommends a feasible study location by considering walking time, available study time, and preferences such as quietness, collaboration, coffee access, and power outlets.

## Features

- Select the locations and times of two consecutive classes
- Calculate the available time between classes
- Recommend a feasible study location
- Support quiet, collaborative, coffee, and outlet preferences
- Estimate walking and study time
- Display the recommended route on an interactive campus map
- Compare alternative study spaces
- Load campus-location information from a CSV dataset

## Recommendation Logic

For each candidate study space, Route2Study estimates:

1. Walking time from the first class to the study space
2. Walking time from the study space to the next class
3. Remaining study time
4. Match with the user's preferred study environment

Locations that provide fewer than 15 minutes of study time are removed. The remaining locations are ranked using a weighted scoring function:

Score = Study Time + 15 × Preference Match + 2 × Outlet Score − 0.5 × Walking Time

## Tech Stack

- Python
- Streamlit
- pandas
- Folium
- OpenStreetMap
- Git and GitHub

## Getting Started

1. Clone the repository:

   git clone https://github.com/haodongy-ee/Route2Study.git

2. Enter the project directory:

   cd Route2Study

3. Install the dependencies:

   python -m pip install -r requirements.txt

4. Run the application:

   python -m streamlit run app.py

## Current Limitations

- Walking time is estimated from straight-line distance
- Route lines do not yet follow the real pedestrian network
- Campus locations and preference scores are manually defined

## Roadmap

- Implement street-level shortest-path routing with NetworkX
- Expand and validate the campus-location dataset
- Add class schedule import
- Formulate study-space selection as an optimization problem
- Deploy the application online

## Author

Haodong Yang  
Master's Student in Electrical Engineering  
University of Pennsylvania