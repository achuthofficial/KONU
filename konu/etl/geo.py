"""Offline reverse geocoding from India Post pincode boundary polygons.

Measured on this dataset (see README): polygon containment resolves *district*
well (88% coverage, ~80% agreement with RERA's district) but resolves *pincode*
poorly (41%), because the listings' coordinates are locality centroids -- 84k
rows share only 8.4k distinct points, and 54% of shared points carry more than
one real pincode. So polygons supply district, candidate pincodes, and a
cross-check on the imputed pincode; they do not fill Pincode itself.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import shapely
from shapely.geometry import shape
from shapely.strtree import STRtree

from ..paths import ROOT

GEOJSON_FILES = ["telangana.geojson", "andhra-pradesh.geojson"]
NEAREST_RADIUS_DEG = 5.0 / 111.0  # ~5km, covers centroid jitter
N_CANDIDATES = 3


class PincodeZones:
    """Spatial index over pincode polygons, built once and queried in bulk."""

    def __init__(self, ref_dir: Path | None = None):
        ref_dir = ref_dir or ROOT / "data" / "reference"
        polys, pins, dists = [], [], []
        for name in GEOJSON_FILES:
            path = ref_dir / name
            if not path.exists():
                continue
            for feat in json.load(open(path))["features"]:
                geom = shape(feat["geometry"])
                props = feat["properties"]
                pincode = str(props.get("pincode", "")).strip()
                if pincode and geom.is_valid:
                    polys.append(geom)
                    pins.append(pincode)
                    dists.append(str(props.get("district", "")).strip() or None)
        self.polygons = np.array(polys, dtype=object)
        self.pincodes = np.array(pins)
        self.districts = np.array(dists, dtype=object)
        self.tree = STRtree(self.polygons) if len(self.polygons) else None

    def __len__(self) -> int:
        return len(self.polygons)

    def _points(self, df: pd.DataFrame):
        has = df["Latitude"].notna() & df["Longitude"].notna()
        pts = shapely.points(df.loc[has, "Longitude"].to_numpy(),
                             df.loc[has, "Latitude"].to_numpy())
        return pts, df.index[has]

    def containing(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        """Pincode and district of the polygon each coordinate falls inside."""
        if self.tree is None:
            empty = pd.Series(index=df.index, dtype=object)
            return empty, empty.copy()
        pts, idx = self._points(df)
        pi, gi = self.tree.query(pts, predicate="within")
        pin = pd.Series(self.pincodes[gi], index=idx[pi]).groupby(level=0).first()
        dis = pd.Series(self.districts[gi], index=idx[pi]).groupby(level=0).first()
        return pin.reindex(df.index), dis.reindex(df.index)

    def nearest_candidates(self, df: pd.DataFrame, n: int = N_CANDIDATES) -> pd.Series:
        """Comma-joined n nearest pincode zones, nearest first (distance 0 = inside)."""
        if self.tree is None:
            return pd.Series(index=df.index, dtype=object)
        pts, idx = self._points(df)
        buffered = shapely.buffer(pts, NEAREST_RADIUS_DEG, quad_segs=4)
        pi, gi = self.tree.query(buffered, predicate="intersects")
        cand = pd.DataFrame({"row": idx[pi], "pincode": self.pincodes[gi],
                             "dist": shapely.distance(pts[pi], self.polygons[gi])})
        cand = cand.sort_values(["row", "dist"]).drop_duplicates(["row", "pincode"])
        top = cand.groupby("row").head(n).groupby("row")["pincode"].apply(lambda s: ",".join(s))
        return top.reindex(df.index)


def attach_geo_columns(df: pd.DataFrame, zones: PincodeZones | None = None) -> pd.DataFrame:
    """Add district_from_geo, Possible_Pincodes, and pincode_matches_polygon."""
    zones = zones or PincodeZones()
    df = df.copy()
    if not len(zones):
        return df

    poly_pin, poly_district = zones.containing(df)
    df["district_from_geo"] = poly_district
    df["Possible_Pincodes"] = zones.nearest_candidates(df)

    # Independent cross-check: does the imputed pincode agree with the polygon
    # the coordinate sits in? Null where either side is unavailable.
    both = df["Pincode"].notna() & poly_pin.notna()
    df["pincode_matches_polygon"] = pd.Series(pd.NA, index=df.index, dtype="boolean")
    df.loc[both, "pincode_matches_polygon"] = (
        df.loc[both, "Pincode"].astype(str) == poly_pin[both].astype(str))
    return df
