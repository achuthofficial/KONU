"""Missing-value imputation.

Each column is imputed by the method its own structure justifies, and every
imputed column carries a `<column>_was_missing` flag. Missingness here isn't
necessarily random, so a model should be able to tell an imputed value from
an observed one rather than treating them identically.

Methods, and why each one:

  group-median by BHK  -- Bathrooms/Balconies/Car_Parking/Floor_Number/
      Total_Floors/Property_Age_Years all scale with unit size, so imputing
      a missing Bathrooms with 0, or with the same global median whether the
      unit is a 1BHK or a 5BHK, systematically biases the wrong rows.
  bucketed median      -- BHK itself, from Area_Sqft quantile buckets (can't
      group a column by itself).
  layered pincode      -- society mode -> spatial KNN on lat/long -> locality
      mode. Measured on held-out observed pincodes: ~68% accurate at ~99.8%
      coverage, so imputed pincodes are usable as a coarse geographic feature
      but are NOT ground truth -- see Pincode_impute_source / _was_missing.
      Locality mode alone was only ~55% (a locality spans a median of 7
      pincodes); society mode alone ~70% but covers only ~88% of rows.
  locality-median geo  -- Latitude/Longitude from the locality's own centroid,
      falling back to the pincode centroid.
  time-group median    -- Cement/Steel prices are macro commodity series, so
      the right neighbour is the same month, not the same property.
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd
from sklearn.neighbors import KNeighborsClassifier

GEO_KNN_NEIGHBOURS = 15


def group_median_impute(df: pd.DataFrame, col: str, group_col: str) -> tuple[pd.Series, pd.Series]:
    was_missing = df[col].isna()
    group_median = df.groupby(group_col)[col].transform("median")
    filled = df[col].fillna(group_median).fillna(df[col].median())
    return filled, was_missing


def bucketed_median_impute(df: pd.DataFrame, col: str, bucket_on: str, n_bins: int = 5) -> tuple[pd.Series, pd.Series]:
    """Like group_median_impute, but groups by quantile buckets of a continuous
    column (used for BHK, imputed from Area_Sqft buckets rather than a group
    of itself).
    """
    was_missing = df[col].isna()
    buckets = pd.qcut(df[bucket_on], q=n_bins, duplicates="drop")
    group_median = df.groupby(buckets, observed=True)[col].transform("median")
    filled = df[col].fillna(group_median).fillna(df[col].median())
    return filled.round(), was_missing


_PLACE_SUFFIX = re.compile(r"[\s,]+(hyderabad|telangana|india)\s*$", re.IGNORECASE)


def normalize_place(value) -> str | None:
    """Locality/society keys for mode lookups.

    The same locality shows up as "Alwal" and "Alwal Hyderabad"; matching on
    the raw string leaves the suffixed variant with no pincode to inherit even
    though the plain one is well covered.
    """
    if pd.isna(value):
        return None
    s = str(value).strip().lower()
    for _ in range(2):
        s = _PLACE_SUFFIX.sub("", s).strip()
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s or None


def _mode_map(df: pd.DataFrame, key: str, value: str) -> pd.Series:
    sub = df[df[key].notna() & df[value].notna()]
    if sub.empty:
        return pd.Series(dtype=object)
    return sub.groupby(key)[value].agg(lambda s: s.mode().iloc[0])


def impute_pincode(df: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Layered pincode imputation. Returns (pincode, was_missing, source).

    Pincodes are stored as 6-character strings -- as a float they pick up
    artifacts like 500073.0, and they are a categorical geographic code, not
    a quantity to do arithmetic on.
    """
    pin = df["Pincode"]
    pin = pin.where(pin.isna(), pin.astype("Float64").astype("Int64").astype(str))
    was_missing = pin.isna()

    keys = df.assign(
        _society_key=df["Society"].map(normalize_place),
        _locality_key=df["Locality"].map(normalize_place),
        _pin=pin,
    )
    observed = keys[keys["_pin"].notna()]

    society_mode = _mode_map(observed, "_society_key", "_pin")
    locality_mode = _mode_map(observed, "_locality_key", "_pin")

    filled = pin.copy()
    source = pd.Series(np.where(was_missing, None, "observed"), index=df.index, dtype=object)

    need = filled.isna()
    from_society = keys.loc[need, "_society_key"].map(society_mode)
    filled.loc[need] = from_society
    source.loc[need & from_society.notna().reindex(df.index, fill_value=False)] = "society_mode"

    geo_train = observed[observed["Latitude"].notna() & observed["Longitude"].notna()]
    need = filled.isna() & df["Latitude"].notna() & df["Longitude"].notna()
    if need.any() and len(geo_train) > GEO_KNN_NEIGHBOURS:
        knn = KNeighborsClassifier(n_neighbors=GEO_KNN_NEIGHBOURS, weights="distance")
        knn.fit(geo_train[["Latitude", "Longitude"]], geo_train["_pin"])
        filled.loc[need] = knn.predict(df.loc[need, ["Latitude", "Longitude"]])
        source.loc[need] = "geo_knn"

    need = filled.isna()
    from_locality = keys.loc[need, "_locality_key"].map(locality_mode)
    filled.loc[need] = from_locality
    source.loc[need & from_locality.notna().reindex(df.index, fill_value=False)] = "locality_mode"

    source = source.fillna("unimputed")
    return filled, was_missing, source


def impute_geo(df: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Latitude/Longitude from the locality centroid, then the pincode
    centroid. Returns (lat, lon, was_missing).
    """
    was_missing = df["Latitude"].isna() | df["Longitude"].isna()
    lat, lon = df["Latitude"], df["Longitude"]
    for key in ["Locality", "Pincode"]:
        if key not in df.columns:
            continue
        lat = lat.fillna(df.groupby(key)["Latitude"].transform("median"))
        lon = lon.fillna(df.groupby(key)["Longitude"].transform("median"))
    return lat.fillna(lat.median()), lon.fillna(lon.median()), was_missing


def impute_by_time_group(df: pd.DataFrame, col: str, time_cols: list[str]) -> tuple[pd.Series, pd.Series]:
    """Median within the same time period -- for macro series (commodity
    prices) whose correct neighbour is the same month, not the same property.
    """
    was_missing = df[col].isna()
    filled = df[col]
    for tcol in time_cols:
        if tcol in df.columns:
            filled = filled.fillna(df.groupby(tcol)[col].transform("median"))
    return filled.fillna(df[col].median()), was_missing
