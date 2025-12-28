import streamlit as st
import pandas as pd
import mgrs
import folium
import geopandas as gpd
from shapely.geometry import Polygon
from shapely.ops import unary_union
from streamlit_folium import st_folium
import json


# Page config
st.set_page_config(layout="wide")

st.markdown("""
**Site Detections**
""")

# Load data
JSON_PATH = "site_classifications.json"

with open(JSON_PATH, "r") as f:
    data = json.load(f)

df = pd.DataFrame(data["sites"])

df["target_grid"] = df["target_grid"].astype(str)
df["zone"] = df["target_grid"].str[:2]
df["zone_band"] = df["target_grid"].str[:3]


# Convert MGRS → Lat/Lon
mgrs_converter = mgrs.MGRS()

def mgrs_to_latlon(code):
    try:
        lat, lon = mgrs_converter.toLatLon(code)
        return pd.Series({"lat": lat, "lon": lon})
    except Exception:
        return pd.Series({"lat": None, "lon": None})

df = pd.concat([df, df["target_grid"].apply(mgrs_to_latlon)], axis=1)
df = df.dropna(subset=["lat", "lon"])


# Sidebar controls
st.sidebar.header("Filters")

site_types = sorted(df["predicted_label"].unique())

selected_site_type = st.sidebar.multiselect(
    "Site Type",
    options=site_types,
    default=site_types
)

view_mode = st.sidebar.radio(
    "View Mode",
    ["Grid View", "Theater Command View"]
)
filtered_df = df[df["predicted_label"].isin(selected_site_type)]

# Latitude band definitions
LAT_BANDS = {
    "C": (-80, -72), "D": (-72, -64), "E": (-64, -56),
    "F": (-56, -48), "G": (-48, -40), "H": (-40, -32),
    "J": (-32, -24), "K": (-24, -16), "L": (-16, -8),
    "M": (-8, 0),    "N": (0, 8),     "P": (8, 16),
    "Q": (16, 24),   "R": (24, 32),   "S": (32, 40),
    "T": (40, 48),   "U": (48, 56),   "V": (56, 64),
    "W": (64, 72),   "X": (72, 84)
}


# Theater Command definitions
THEATER_COMMANDS = {
    "Western TC": ["45T", "45S", "46S"],
    "Eastern TC": ["48R", "50R"]
}


# Grid polygon builder
def grid_zone_polygon(zone_band):
    zone = int(zone_band[:2])
    band = zone_band[2]

    lat_min, lat_max = LAT_BANDS[band]
    lon_min = (zone - 1) * 6 - 180
    lon_max = zone * 6 - 180

    return Polygon([
        (lon_min, lat_min),
        (lon_max, lat_min),
        (lon_max, lat_max),
        (lon_min, lat_max),
        (lon_min, lat_min)
    ])


# Grid GeoDataFrame
all_grids = sorted(df["zone_band"].unique())

grid_gdf = gpd.GeoDataFrame(
    {"grid": all_grids},
    geometry=[grid_zone_polygon(g) for g in all_grids],
    crs="EPSG:4326"
)


# Theater Command GeoDataFrame 
tc_records = []

for tc_name, grids in THEATER_COMMANDS.items():
    polys = [grid_zone_polygon(g) for g in grids]
    tc_records.append({
        "theater": tc_name,
        "geometry": unary_union(polys)
    })

tc_gdf = gpd.GeoDataFrame(tc_records, crs="EPSG:4326")


# Map centering
DEFAULT_MAP_CENTER = {
    "lat": 34.0,
    "lon": 90.0,   # slightly right-shifted
    "zoom": 5
}

center_lat = DEFAULT_MAP_CENTER["lat"]
center_lon = DEFAULT_MAP_CENTER["lon"]
# Create Folium map

folium_map = folium.Map(
    location=[center_lat, center_lon],
    zoom_start=4,
    tiles="CartoDB dark_matter"
)


# Render correct spatial layer
if view_mode == "Theater Command View":

    folium.GeoJson(
        tc_gdf,
        name="Theater Commands",
        style_function=lambda x: {
            "fillColor": "#ffaa00",
            "color": "#ffaa00",
            "weight": 2,
            "fillOpacity": 0.18
        },
        highlight_function=lambda x: {
            "weight": 3,
            "fillOpacity": 0.25
        },
        tooltip=folium.GeoJsonTooltip(fields=["theater"])
    ).add_to(folium_map)

else:  # Grid View

    folium.GeoJson(
        grid_gdf,
        name="Grid Zones",
        style_function=lambda x: {
            "fillOpacity": 0.08,
            "weight": 1,
            "color": "#ff3366"
        },
        highlight_function=lambda x: {
            "weight": 3,
            "fillOpacity": 0.15
        },
        tooltip=folium.GeoJsonTooltip(fields=["grid"])
    ).add_to(folium_map)

# Add site detections
for _, row in filtered_df.iterrows():
    folium.CircleMarker(
        location=[row["lat"], row["lon"]],
        radius=5,
        color="cyan",
        fill=True,
        fill_opacity=0.9,
        popup=(
            f"<b>Grid:</b> {row['zone_band']}<br>"
            f"<b>Predicted:</b> {row['predicted_label']}<br>"
            f"<b>Confidence:</b> {row['confidence']:.2f}"
        )
    ).add_to(folium_map)


# Render map & capture clicks
map_state = st_folium(folium_map, width=1920, height=520)

clicked_grid = None
clicked_theater = None

if (
    map_state
    and map_state.get("last_active_drawing")
    and map_state["last_active_drawing"].get("properties")
):
    props = map_state["last_active_drawing"]["properties"]

    if view_mode == "Theater Command View" and "theater" in props:
        clicked_theater = props["theater"]

    if view_mode == "Grid View" and "grid" in props:
        clicked_grid = props["grid"]


# Table filtering
if clicked_theater:
    grids = THEATER_COMMANDS[clicked_theater]
    table_df = df[df["zone_band"].isin(grids)]
    st.subheader(f"Detected Sites – {clicked_theater}")

elif clicked_grid:
    table_df = df[df["zone_band"] == clicked_grid]
    st.subheader(f"Detected Sites – Grid {clicked_grid}")

else:
    table_df = df
    st.subheader("Detected Sites – All Sites")

st.dataframe(
    table_df[
        [
            "image_name",
            "target_grid",
            "true_label",
            "predicted_label",
            "confidence",
            "outcome"
        ]
    ],
    use_container_width=True
)
