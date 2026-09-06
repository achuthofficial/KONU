"""Transform: merge with RERA, clean, impute, engineer features."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..matching.entity_match import match_listings_to_rera
from .clean import collapse_to_top_n, derive_deal_type, winsorize_by_group
from .geo import attach_geo_columns
from .impute import (bucketed_median_impute, group_median_impute, impute_by_time_group,
                      impute_geo, impute_pincode)

MAX_DATA_LOSS_PCT = 5.0

# These scale with unit size, so they're imputed by median within BHK.
GROUP_MEDIAN_IMPUTE_COLS = [
    "Bathrooms", "Balconies", "Car_Parking", "Floor_Number", "Total_Floors", "Property_Age_Years",
]

MATERIAL_PRICE_COLS = ["Cement_Price_Rs_per_bag_50kg", "Steel_TMT_Price_Rs_per_tonne"]

LOW_CARD_CATS = [
    "Furnishing", "Facing", "Ownership", "Overlooking", "Age_Group",
    "Construction_Status", "rera_project_status", "rera_project_type",
    "district_from_geo",
]

# Deterministic functions of the target -- kept for reference, excluded from features.
LEAKAGE_COLS = ["Price_Cr", "PricePerSqft"]

# Only populated where a listing matched a RERA project; filling them would fabricate a record.
NEVER_IMPUTE_COLS = [
    "rera_project_name", "rera_promoter_name", "rera_approved_date",
    "rera_proposed_completion_date", "rera_pincode",
]

# Year/Month are used to impute the commodity series, then dropped: they track the scrape date.
DROP_COLS = [
    "_links", "Transaction", "YearMonth", "Year", "Month", "Full_Address",
    "match_score", "match_method", "rera_token",
]


def to_sale_only(listings: pd.DataFrame) -> pd.DataFrame:
    """Sale-only deduplicated subset, used by the price-model notebooks (03-05)."""
    df = listings.copy()
    df["deal_type"] = derive_deal_type(df["URL"])
    return df[df["deal_type"] == "Sale"].drop_duplicates(subset="URL").drop(columns=["deal_type"])


def drop_invalid_rows(listings: pd.DataFrame) -> pd.DataFrame:
    """The only row-drop: no valid price or area means the row can't be used or honestly imputed."""
    price_ok = listings["Price_INR"].notna() & (listings["Price_INR"] > 0)
    area_ok = listings["Area_Sqft"].notna() & (listings["Area_Sqft"] > 0)
    return listings[price_ok & area_ok].copy()


def clean_and_engineer(merged: pd.DataFrame) -> pd.DataFrame:
    df = merged.copy()

    # deal_type first: prices must be capped within deal type, not across it.
    df["deal_type"] = derive_deal_type(df["URL"])
    df["is_duplicate_url"] = df["URL"].duplicated(keep=False)
    df = winsorize_by_group(df, ["Price_INR", "Area_Sqft"], "deal_type")

    # BHK first, since it's the grouping key for the rest.
    df["BHK"], df["BHK_was_missing"] = bucketed_median_impute(df, "BHK", "Area_Sqft", n_bins=5)
    for col in GROUP_MEDIAN_IMPUTE_COLS:
        df[col], df[f"{col}_was_missing"] = group_median_impute(df, col, "BHK")

    # Pincode before geo: its KNN must train on observed coordinates only.
    df["Pincode"], df["Pincode_was_missing"], df["Pincode_impute_source"] = impute_pincode(df)
    df["Latitude"], df["Longitude"], df["geo_was_missing"] = impute_geo(df)

    for col in MATERIAL_PRICE_COLS:
        df[col], df[f"{col}_was_missing"] = impute_by_time_group(df, col, ["YearMonth", "Year"])

    for col in ["Society", "Locality"]:
        df[col] = df[col].fillna("Unknown")
    for col in ["rera_project_status", "rera_project_type", "rera_district"]:
        df[col] = df[col].fillna("Not Matched")

    # Recomputed, not imputed: it is definitionally this ratio and both inputs are guaranteed.
    df["PricePerSqft"] = df["Price_INR"] / df["Area_Sqft"]
    df = winsorize_by_group(df, ["PricePerSqft"], "deal_type")

    # Polygon-derived geography: district, candidate pincodes, and a cross-check
    # on the imputed pincode. Polygons don't fill Pincode -- see geo.py.
    df = attach_geo_columns(df)

    df["log_price"] = np.log1p(df["Price_INR"])
    df["floor_ratio"] = (df["Floor_Number"] / df["Total_Floors"].replace(0, np.nan)).fillna(0).clip(0, 1)
    df["has_rera_match"] = df["rera_project_name"].notna().astype(int)

    for col in LOW_CARD_CATS:
        df[col] = collapse_to_top_n(df[col].fillna("Unknown"), n=10)

    return df.drop(columns=[c for c in DROP_COLS if c in df.columns])


def build_feature_matrix(cleaned: pd.DataFrame) -> pd.DataFrame:
    """One-hot encoded and leakage-free. Price_INR/log_price remain as targets."""
    df = cleaned.drop(columns=[c for c in LEAKAGE_COLS + ["URL", "Possible_Pincodes"]
                                if c in cleaned.columns])
    # Pincode stays a string like Locality/Society: ~180 categories, target-encode at train time.
    one_hot = [c for c in LOW_CARD_CATS + ["deal_type", "Pincode_impute_source"] if c in df.columns]
    return pd.get_dummies(df, columns=one_hot, prefix=one_hot)


def run(listings: pd.DataFrame, rera: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Full transform. Raises if row loss exceeds MAX_DATA_LOSS_PCT."""
    n_start = len(listings)
    merged, match_report = match_listings_to_rera(drop_invalid_rows(listings), rera)
    cleaned = clean_and_engineer(merged)
    features = build_feature_matrix(cleaned)

    loss_pct = round(100 * (n_start - len(cleaned)) / n_start, 2)
    match_report |= {"n_listings_start": n_start, "n_listings_final": len(cleaned),
                     "data_loss_pct": loss_pct}
    if loss_pct > MAX_DATA_LOSS_PCT:
        raise ValueError(f"data loss {loss_pct}% exceeds the {MAX_DATA_LOSS_PCT}% budget "
                          f"({n_start - len(cleaned):,} of {n_start:,} rows dropped)")
    return cleaned, features, match_report
