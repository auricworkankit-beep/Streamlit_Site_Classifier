import streamlit as st
import pandas as pd
import mgrs
import folium
from pathlib import Path
import geopandas as gpd
from shapely.geometry import Polygon
from streamlit_folium import st_folium
import json
from lxml import etree

from src.mgrs.mgrs_zone_band import (
    build_mgrs_zone_band_layer,
    get_mgrs_zone_band_limits
)

# SINGLE AUTHORITY: BASE MAP VIEW CONTROLLER
def create_base_map():
    """
    This function is the ONLY place that controls:
    - Default map view
    - Zoom limits
    - Pan limits
    """
    # FIXED VIEW BOX (make changes the default view here in future when expanding the area of interest from China to Pakistan and so, current centered on the Indian subcontinent)
    VIEW_BOUNDS = [
        [5.0, 55.0],     # South-West  (lat, lon)
        [62.0, 135.0],   # North-East
    ]

    DEFAULT_ZOOM = 4

    m = folium.Map(
        location=[30.0, 85.0],   # temporary, overridden by fit_bounds
        zoom_start=DEFAULT_ZOOM,
        tiles=None,
        zoom_control=True,
        max_bounds=True,
    )

    # Base tiles
    folium.TileLayer(
        tiles="CartoDB dark_matter",
        no_wrap=True,
        continuous_world=False
    ).add_to(m)

    # LOCK DEFAULT VIEW
    m.fit_bounds(VIEW_BOUNDS, padding=(20, 20))


    m.options["maxBounds"] = VIEW_BOUNDS
    m.options["maxBoundsViscosity"] = 1.0   # hard lock at default zoom
    m.options["minZoom"] = DEFAULT_ZOOM     # cannot zoom out
    m.options["worldCopyJump"] = False

    return m

# Page config
st.set_page_config(layout="wide")
st.markdown("**Site Detections**")


# Paths
JSON_PATH = "site_classifications.json"

TC_GEOJSON_FILES = {
    "North TC": "data/china_pla_ground_forces_north_TC.geojson",
    "East TC":  "data/china_pla_ground_forces_east_TC.geojson",
    "South TC": "data/china_pla_ground_forces_south_TC.geojson",
    "West TC":  "data/china_pla_ground_forces_west_TC.geojson",
    "Central TC": "data/china_pla_ground_forces_center_TC.geojson",
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
    path = Path(path)
    with path.open("r", encoding="utf-8") as f:
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

INDIA_BOUNDS_PATH = "data/india_international_bounds.geojson"

@st.cache_data(show_spinner=False)
def load_india_bounds():
    with open(INDIA_BOUNDS_PATH, "r") as f:
        return json.load(f)

from shapely.geometry import Point, shape
from shapely.ops import unary_union

@st.cache_data(show_spinner=False)
def build_tc_geometry_map(tc_files: dict) -> dict:
    tc_geom_map = {}

    for tc_name, tc_path in tc_files.items():
        tc_path = Path(tc_path)

        if not tc_path.exists():
            raise FileNotFoundError(f"Missing TC file: {tc_path}")

        with tc_path.open("r", encoding="utf-8") as f:
            geojson = json.load(f)

        geoms = [shape(feat["geometry"]) for feat in geojson["features"]]
        tc_geom_map[tc_name] = unary_union(geoms)

    return tc_geom_map

@st.cache_resource(show_spinner=False)
def load_unified_site_polygons(kmz_path: str):
    import zipfile
    from lxml import etree
    from shapely.geometry import shape
    from shapely.ops import unary_union

    with zipfile.ZipFile(kmz_path) as z:
        kml_name = [n for n in z.namelist() if n.endswith(".kml")][0]
        kml_data = z.read(kml_name)

    root = etree.fromstring(kml_data)
    ns = {"kml": "http://www.opengis.net/kml/2.2"}

    site_polys = {}

    for pm in root.findall(".//kml:Placemark", namespaces=ns):
        name = pm.find("kml:name", namespaces=ns)
        if name is None:
            continue

        full_name = name.text.strip()
        mgrs = full_name.split("_")[0]   # 🔑 KEY FACT

        polygon = pm.find("kml:Polygon", namespaces=ns)
        if polygon is None:
            continue

        coords_text = polygon.find(
            ".//kml:coordinates", namespaces=ns
        ).text.strip()

        coords = []
        for c in coords_text.split():
            lon, lat, *_ = map(float, c.split(","))
            coords.append((lon, lat))

        site_polys[mgrs] = {
            "geometry": {
                "type": "Polygon",
                "coordinates": [coords]
            },
            "name": full_name
        }

    return site_polys

# Load data
df = load_sites_dataframe(JSON_PATH)
TC_GEOMS = build_tc_geometry_map(TC_GEOJSON_FILES)

SITE_POLY_PATH = "data/Unified_Site_Poly.kmz"
SITE_POLYGONS = load_unified_site_polygons(SITE_POLY_PATH)


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
    ["Base View", "Theater Command View"]
)

selected_tc = None

# Theater Command selector (only when relevant)
if view_mode == "Theater Command View":
    selected_tc = st.sidebar.selectbox(
        "Select Theater Command",
        ["All"] + list(TC_GEOJSON_FILES.keys())
    )

# MGRS toggle (ALWAYS visible)
show_mgrs = st.sidebar.checkbox(
    "Show MGRS Grid",
    value=False
)

# Attribute filter (Site Type) 
filtered_df = df[df["predicted_label"].isin(selected_site_type)]
# Spatial filter (Theater Command)
if (
    view_mode == "Theater Command View"
    and selected_tc not in (None, "All")
):
    tc_geom = TC_GEOMS[selected_tc]

    filtered_df = filtered_df[
        filtered_df.apply(
            lambda r: tc_geom.contains(Point(r["lon"], r["lat"])),
            axis=1
        )
    ]

# Map setup
folium_map = create_base_map()

# View normalization / Theater Command zoom control
if (
    view_mode == "Theater Command View"
    and selected_tc not in (None, "All")
):
    tc_geom = TC_GEOMS[selected_tc]
    minx, miny, maxx, maxy = tc_geom.bounds

    # 🔓 TEMPORARILY RELAX GLOBAL VIEW LOCK
    folium_map.options["maxBounds"] = None
    folium_map.options["maxBoundsViscosity"] = 0.0

    folium_map.fit_bounds(
        [[miny, minx], [maxy, maxx]],
        padding=(0, 0)
    )

    # Allow deeper zoom while focused
    folium_map.options["minZoom"] = 5

# Theater Command baselayer (For China as of now)
if view_mode == "Theater Command View":
    tc_layer = folium.FeatureGroup("Theater Commands", overlay=False)

    for tc_name, tc_path in TC_GEOJSON_FILES.items():

        # Skip non-selected TCs when a specific one is chosen
        if selected_tc not in (None, "All") and tc_name != selected_tc:
            continue

        raw_geojson = load_geojson(tc_path)

        # Core logic:
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


# MGRS overlay (toggleable)
if view_mode == "Theater Command View" and show_mgrs:
    mgrs_bounds = get_mgrs_zone_band_limits()

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


# Site markers (always visible)
for _, row in filtered_df.iterrows():
    mgrs = row["target_grid"]

    site = SITE_POLYGONS.get(mgrs)
    if site is None:
        continue

    folium.GeoJson(
        site["geometry"],
        style_function=lambda _: {
            "fillColor": "#00ffff",
            "color": "#00ffff",
            "weight": 1,
            "fillOpacity": 0.6,
        },
        tooltip=(
            f"<b>MGRS:</b> {mgrs}<br>"
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
    st_folium(folium_map, width=1200, height=720)


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
    width="stretch"
)