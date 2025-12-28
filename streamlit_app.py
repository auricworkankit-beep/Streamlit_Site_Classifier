import streamlit as st
import pandas as pd
import mgrs
import folium
import geopandas as gpd
from shapely.geometry import Polygon
from streamlit_folium import st_folium
import json

from src.mgrs.mgrs_zone_band import (
    build_mgrs_zone_band_layer,
    get_mgrs_zone_band_limits
)

# Page config
st.set_page_config(layout="wide")
st.markdown("**Site Detections**")


# Paths
JSON_PATH = "site_classifications.json"

TC_GEOJSON_FILES = {
    "North TC": "/workspaces/Streamlit_Site_Classifier/data/china_pla_ground_forces_north_TC.geojson",
    "East TC":  "/workspaces/Streamlit_Site_Classifier/data/china_pla_ground_forces_east_TC.geojson",
    "South TC": "/workspaces/Streamlit_Site_Classifier/data/china_pla_ground_forces_south_TC.geojson",
    "West TC":  "/workspaces/Streamlit_Site_Classifier/data/china_pla_ground_forces_west_TC.geojson",
    "Central TC": "/workspaces/Streamlit_Site_Classifier/data/china_pla_ground_forces_center_TC.geojson",
}

TC_COLORS = {
    "North TC":   "#1f77b4",
    "East TC":    "#2ca02c",
    "South TC":   "#ff7f0e",
    "West TC":    "#9467bd",
    "Central TC": "#d62728",
}


# Cached loaders
@st.cache_data(show_spinner=False)
def load_geojson(path: str) -> dict:
    with open(path, "r") as f:
        return json.load(f)


@st.cache_data(show_spinner=False)
def load_sites_dataframe(json_path: str) -> pd.DataFrame:
    with open(json_path, "r") as f:
        data = json.load(f)

    df = pd.DataFrame(data["sites"])

    df["target_grid"] = df["target_grid"].astype(str)
    df["zone_band"] = df["target_grid"].str[:3]

    mgrs_converter = mgrs.MGRS()

    def mgrs_to_latlon(code):
        try:
            lat, lon = mgrs_converter.toLatLon(code)
            return pd.Series({"lat": lat, "lon": lon})
        except Exception:
            return pd.Series({"lat": None, "lon": None})

    df = pd.concat([df, df["target_grid"].apply(mgrs_to_latlon)], axis=1)
    return df.dropna(subset=["lat", "lon"])


@st.cache_data(show_spinner=False)
def get_mgrs_layer_cached():
    return build_mgrs_zone_band_layer()


#Unified TC Boundary in Default TC view, but upon TC selection, we break the internal boundaries into provinces
from shapely.geometry import shape, mapping
from shapely.ops import unary_union

@st.cache_data(show_spinner=False)
def dissolve_geojson(geojson: dict) -> dict:
    """
    Dissolve all features in a GeoJSON into a single polygon feature.
    """
    geoms = [shape(f["geometry"]) for f in geojson["features"]]
    dissolved = unary_union(geoms)

    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": mapping(dissolved),
                "properties": {}
            }
        ]
    }

INDIA_BOUNDS_PATH = "/workspaces/Streamlit_Site_Classifier/data/india_international_bounds.geojson"

@st.cache_data(show_spinner=False)
def load_india_bounds():
    with open(INDIA_BOUNDS_PATH, "r") as f:
        return json.load(f)

# Load data
df = load_sites_dataframe(JSON_PATH)


# Sidebar controls
st.sidebar.header("Filters")

site_types = sorted(df["predicted_label"].unique())
selected_site_type = st.sidebar.multiselect(
    "Site Type",
    site_types,
    default=site_types
)

view_mode = st.sidebar.radio(
    "View Mode",
    ["Grid View", "Theater Command View"]
)

selected_tc = None
show_mgrs = False

if view_mode == "Theater Command View":
    selected_tc = st.sidebar.selectbox(
        "Select Theater Command",
        ["All"] + list(TC_GEOJSON_FILES.keys())
    )
    show_mgrs = st.sidebar.checkbox("Show MGRS Grid", value=False)

filtered_df = df[df["predicted_label"].isin(selected_site_type)]


# Map setup
DEFAULT_VIEW = {"lat": 35.0, "lon": 85.0, "zoom": 4}

folium_map = folium.Map(
    location=[DEFAULT_VIEW["lat"], DEFAULT_VIEW["lon"]],
    zoom_start=DEFAULT_VIEW["zoom"],
    tiles=None,
    zoom_control=True
)

folium.TileLayer(
    tiles="CartoDB dark_matter",
    no_wrap=True,
    continuous_world=False
).add_to(folium_map)

# --------------------------------------------------
# Theater Command baselayer
# --------------------------------------------------
if view_mode == "Theater Command View":
    tc_layer = folium.FeatureGroup("Theater Commands", overlay=False)

    for tc_name, tc_path in TC_GEOJSON_FILES.items():

        # Skip non-selected TCs when a specific one is chosen
        if selected_tc not in (None, "All") and tc_name != selected_tc:
            continue

        raw_geojson = load_geojson(tc_path)

        # 🔑 Core logic:
        # - Default ("All") → dissolve → no internal boundaries
        # - Specific TC → original geometry → internal boundaries visible
        if selected_tc in (None, "All"):
            geojson_to_render = dissolve_geojson(raw_geojson)
            border_weight = 2
        else:
            geojson_to_render = raw_geojson
            border_weight = 1

        color = TC_COLORS.get(tc_name, "#ff0000")

        folium.GeoJson(
            geojson_to_render,
            style_function=lambda f, c=color, w=border_weight: {
                "fillColor": c,
                "color": c,
                "weight": w,
                "fillOpacity": 0.5,
            },
            highlight_function=lambda f, c=color: {
                "weight": 3,
                "color": c,
                "fillOpacity": 0.65,
            },
            tooltip=tc_name,
        ).add_to(tc_layer)

    tc_layer.add_to(folium_map)

# --------------------------------------------------
# MGRS overlay (toggleable)
# --------------------------------------------------
if view_mode == "Theater Command View" and show_mgrs:
    mgrs_bounds = get_mgrs_zone_band_limits()
    folium_map.options["maxBounds"] = mgrs_bounds
    folium_map.options["maxBoundsViscosity"] = 1.0
    folium_map.options["minZoom"] = 2

    folium.GeoJson(
        get_mgrs_layer_cached(),
        name="MGRS Grid",
        style_function=lambda f: {
            "color": "#00ffff",
            "weight": 0.7,
            "fillOpacity": 0.02
        },
        tooltip=folium.GeoJsonTooltip(fields=["mgrs"], aliases=["MGRS"])
    ).add_to(folium_map)

# --------------------------------------------------
# Site markers (always visible)
# --------------------------------------------------
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



# India occlusion layer (ALWAYS ON)
india_geojson = load_india_bounds()

folium.GeoJson(
    india_geojson,
    name="India Occlusion Mask",
    style_function=lambda f: {
        "fillColor": "#000000",
        "color": "#000000",
        "weight": 0,
        "fillOpacity": 1.0,   # fully opaque
    },
    interactive=False  # does NOT block pan/zoom/clicks
).add_to(folium_map)



# Render map (centered)
left, center, right = st.columns([1, 6, 1])
with center:
    map_state = st_folium(folium_map, width=1200, height=620)


# Table
st.subheader("Detected Sites")
st.dataframe(
    filtered_df[
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