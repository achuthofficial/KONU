"""Stage 3: fill missing pincodes and list the 3 nearest candidate zones per coordinate.

Uses the official India Post boundary polygons (GeoJSON) for fully offline
reverse geocoding. Distance is 0 when the point lies inside a polygon.
"""
import json

import numpy as np
import pandas as pd
import shapely
from shapely.geometry import shape
from shapely.strtree import STRtree

from .schema import GEOJSON_FILES

SEARCH_RADIUS_KM = 5.0  # covers coordinate jitter in scraped listings
TOP_N = 3


def load_zones(paths=GEOJSON_FILES):
    polygons, pincodes = [], []
    for path in paths:
        for feature in json.load(open(path))["features"]:
            pincode = str(feature["properties"].get("pincode", "")).strip()
            geom = shape(feature["geometry"])
            if pincode and geom.is_valid:
                polygons.append(geom)
                pincodes.append(pincode)
    return np.array(polygons, dtype=object), np.array(pincodes)


def enrich(df, paths=GEOJSON_FILES):
    """Return `df` with missing Pincode filled and a Possible_Pincodes column added."""
    polygons, pincodes = load_zones(paths)
    tree = STRtree(polygons)

    lat = pd.to_numeric(df["Latitude"], errors="coerce")
    lon = pd.to_numeric(df["Longitude"], errors="coerce")
    has_coords = lat.notna() & lon.notna()
    points = shapely.points(lon[has_coords].to_numpy(), lat[has_coords].to_numpy())
    row_ids = np.flatnonzero(has_coords.to_numpy())

    buffered = shapely.buffer(points, SEARCH_RADIUS_KM / 111.0, quad_segs=4)
    pt_idx, poly_idx = tree.query(buffered, predicate="intersects")
    dist = shapely.distance(points[pt_idx], polygons[poly_idx])
    cand = (pd.DataFrame({"row": row_ids[pt_idx], "pincode": pincodes[poly_idx], "dist": dist})
            .sort_values(["row", "dist"]).drop_duplicates(["row", "pincode"]))
    grouped = cand.groupby("row")["pincode"]
    nearest = grouped.first()
    top = grouped.agg(lambda s: ", ".join(s.head(TOP_N)))

    out = df.reset_index(drop=True)
    positions = out.index
    out["Pincode"] = out["Pincode"].astype("string").fillna(nearest.reindex(positions).astype("string"))
    out["Possible_Pincodes"] = top.reindex(positions)
    return out
