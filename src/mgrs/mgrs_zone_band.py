from shapely.geometry import shape, Polygon, mapping
from shapely.ops import unary_union

ALLOWED_ZONES = range(38, 59)  # 38–58 inclusive
ALLOWED_BANDS = ["N", "P", "Q", "R", "S", "T", "U", "V", "W", "X"]

LAT_BAND_BOUNDS = {
    "N": (0, 8), "P": (8, 16), "Q": (16, 24), "R": (24, 32),
    "S": (32, 40), "T": (40, 48), "U": (48, 56),
    "V": (56, 64), "W": (64, 72), "X": (72, 84),
}

def mgrs_zone_band_feature(zone: int, band: str) -> dict:
    lon_min = (zone - 1) * 6 - 180
    lon_max = lon_min + 6
    lat_min, lat_max = LAT_BAND_BOUNDS[band]

    polygon = Polygon([
        (lon_min, lat_min),
        (lon_max, lat_min),
        (lon_max, lat_max),
        (lon_min, lat_max),
        (lon_min, lat_min),
    ])

    return {
        "type": "Feature",
        "geometry": mapping(polygon),
        "properties": {
            "mgrs": f"{zone}{band}",
            "zone": zone,
            "band": band,
            "level": "zone_band",
        },
    }

def build_mgrs_zone_band_layer() -> dict:
    return {
        "type": "FeatureCollection",
        "features": [
            mgrs_zone_band_feature(z, b)
            for z in ALLOWED_ZONES
            for b in ALLOWED_BANDS
        ],
    }

def get_mgrs_zone_band_limits():
    layer = build_mgrs_zone_band_layer()
    union_geom = unary_union([shape(f["geometry"]) for f in layer["features"]])
    minx, miny, maxx, maxy = union_geom.bounds
    return [[miny, minx], [maxy, maxx]]