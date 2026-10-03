"""Imputation. Each column gets the method its structure justifies, plus a _was_missing flag.

Measured on held-out observed pincodes: society mode 70.6%, spatial KNN 67.6%,
locality mode 54.5%, layered chain 68.5% at 99.8% coverage. See README.
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd
from sklearn.neighbors import KNeighborsClassifier

GEO_KNN_NEIGHBOURS = 15

_PLACE_SUFFIX = re.compile(r"[\s,]+(hyderabad|telangana|india)\s*$", re.IGNORECASE)


def normalize_place(value) -> str | None:
    """Key for place lookups -- "Alwal Hyderabad" must match "Alwal"."""
    if pd.isna(value):
        return None
    s = str(value).strip().lower()
    for _ in range(2):  # twice, to peel "…, Hyderabad, Telangana"
        s = _PLACE_SUFFIX.sub("", s).strip()
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip() or None


def group_median_impute(df: pd.DataFrame, col: str, group_col: str) -> tuple[pd.Series, pd.Series]:
    """Median within the group -- for fields that scale with unit size (bathrooms by BHK)."""
    was_missing = df[col].isna()
    filled = df[col].fillna(df.groupby(group_col)[col].transform("median")).fillna(df[col].median())
    return filled, was_missing


def bucketed_median_impute(df: pd.DataFrame, col: str, bucket_on: str,
                            n_bins: int = 5) -> tuple[pd.Series, pd.Series]:
    """Median within quantile buckets of another column -- for BHK, which can't group by itself."""
    was_missing = df[col].isna()
    buckets = pd.qcut(df[bucket_on], q=n_bins, duplicates="drop")
    filled = df[col].fillna(df.groupby(buckets, observed=True)[col].transform("median"))
    return filled.fillna(df[col].median()).round(), was_missing


def _mode_map(df: pd.DataFrame, key: str, value: str) -> pd.Series:
    sub = df[df[key].notna() & df[value].notna()]
    return sub.groupby(key)[value].agg(lambda s: s.mode().iloc[0]) if not sub.empty else pd.Series(dtype=object)


def impute_pincode(df: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Layered: society mode -> spatial KNN on lat/long -> locality mode. Returns (pincode, was_missing, source)."""
    # Stored as string: a pincode is a categorical geographic code, not a quantity.
    pin = df["Pincode"]
    pin = pin.where(pin.isna(), pin.astype("Float64").astype("Int64").astype(str))
    was_missing = pin.isna()

    keys = df.assign(_society=df["Society"].map(normalize_place),
                     _locality=df["Locality"].map(normalize_place), _pin=pin)
    observed = keys[keys["_pin"].notna()]
    society_mode = _mode_map(observed, "_society", "_pin")
    locality_mode = _mode_map(observed, "_locality", "_pin")

    filled = pin.copy()
    source = pd.Series(np.where(was_missing, None, "observed"), index=df.index, dtype=object)

    need = filled.isna()
    from_society = keys.loc[need, "_society"].map(society_mode)
    filled.loc[need] = from_society
    source.loc[need & from_society.notna().reindex(df.index, fill_value=False)] = "society_mode"

    # Trained on observed coordinates only, so it never learns from imputed geo.
    geo_train = observed[observed["Latitude"].notna() & observed["Longitude"].notna()]
    need = filled.isna() & df["Latitude"].notna() & df["Longitude"].notna()
    if need.any() and len(geo_train) > GEO_KNN_NEIGHBOURS:
        knn = KNeighborsClassifier(n_neighbors=GEO_KNN_NEIGHBOURS, weights="distance")
        knn.fit(geo_train[["Latitude", "Longitude"]], geo_train["_pin"])
        filled.loc[need] = knn.predict(df.loc[need, ["Latitude", "Longitude"]])
        source.loc[need] = "geo_knn"

    need = filled.isna()
    from_locality = keys.loc[need, "_locality"].map(locality_mode)
    filled.loc[need] = from_locality
    source.loc[need & from_locality.notna().reindex(df.index, fill_value=False)] = "locality_mode"

    # Rows with no society, no coordinates and no known locality stay null rather than guessed.
    return filled, was_missing, source.fillna("unimputed")


def impute_geo(df: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Latitude/Longitude from the locality centroid, then the pincode centroid."""
    was_missing = df["Latitude"].isna() | df["Longitude"].isna()
    lat, lon = df["Latitude"], df["Longitude"]
    for key in ["Locality", "Pincode"]:
        if key in df.columns:
            lat = lat.fillna(df.groupby(key)["Latitude"].transform("median"))
            lon = lon.fillna(df.groupby(key)["Longitude"].transform("median"))
    return lat.fillna(lat.median()), lon.fillna(lon.median()), was_missing


def impute_by_time_group(df: pd.DataFrame, col: str, time_cols: list[str]) -> tuple[pd.Series, pd.Series]:
    """Median within the same period -- for macro series whose neighbour is the month, not the property."""
    was_missing = df[col].isna()
    filled = df[col]
    for tcol in time_cols:
        if tcol in df.columns:
            filled = filled.fillna(df.groupby(tcol)[col].transform("median"))
    return filled.fillna(df[col].median()), was_missing
