"""Transform stage: merge listings with RERA, clean, and engineer features.

LEAKAGE_COLS documents columns that are deterministic functions of the
target (Price_Cr = Price_INR / 1e7, PricePerSqft = Price_INR / Area_Sqft):
kept as reference columns on the cleaned frame, but excluded from the
one-hot-encoded feature matrix build_feature_matrix() hands to modeling.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tsrera" / "data_analysis" / "scripts"))
from entity_match import match_listings_to_rera  # noqa: E402

from .clean import collapse_to_top_n, derive_deal_type, filter_percentile_outliers, winsorize
from .impute import bucketed_median_impute, group_median_impute

GROUP_MEDIAN_IMPUTE_COLS = [
    "Bathrooms", "Balconies", "Car_Parking", "Floor_Number", "Total_Floors", "Property_Age_Years",
]

LOW_CARD_CATS = [
    "Furnishing", "Facing", "Ownership", "Overlooking", "Age_Group",
    "Construction_Status", "rera_project_status", "rera_project_type",
]

LEAKAGE_COLS = ["Price_Cr", "PricePerSqft"]

MAX_DATA_LOSS_PCT = 5.0

DROP_COLS = [
    "_links", "Transaction", "YearMonth", "Year", "Month", "Pincode", "Full_Address",
    "match_score", "match_method", "rera_token",
]


def to_sale_only(listings: pd.DataFrame) -> pd.DataFrame:
    """Sale-only, deduplicated subset -- used by the house-price-prediction
    notebooks (03/04/05), which have a data-loss budget to spend because
    their deliverable is specifically a leakage-free sale-price model input.
    Not used by run() below: the general cleaned dataset keeps deal type and
    duplicates as flags instead of dropping them, to stay within a 5%
    data-loss budget on the full listings volume.
    """
    df = listings.copy()
    df["deal_type"] = derive_deal_type(df["URL"])
    df = df[df["deal_type"] == "Sale"].drop_duplicates(subset="URL")
    return df.drop(columns=["deal_type"])


def drop_invalid_rows(listings: pd.DataFrame) -> pd.DataFrame:
    """The only row-drop in the general cleaning path: a listing with no
    valid price or no valid area can't be used for anything price-related,
    and there's no honest way to impute either one. Costs ~3.8% of rows.
    Everything else below is non-destructive (impute, winsorize, flag) so
    the total stays under MAX_DATA_LOSS_PCT.
    """
    price_ok = listings["Price_INR"].notna() & (listings["Price_INR"] > 0)
    area_ok = listings["Area_Sqft"].notna() & (listings["Area_Sqft"] > 0)
    return listings[price_ok & area_ok].copy()


def clean_and_engineer(merged: pd.DataFrame) -> pd.DataFrame:
    df = winsorize(merged, ["Price_INR", "Area_Sqft", "PricePerSqft"])

    df["deal_type"] = derive_deal_type(df["URL"])
    df["is_duplicate_url"] = df["URL"].duplicated(keep=False)

    # BHK is rarely missing and is the strongest available predictor of the
    # columns below, so it's imputed first (from Area_Sqft, since a unit's
    # size is a strong, near-always-present proxy for its BHK count) and then
    # used as the grouping key for everything else.
    df["BHK"], df["BHK_was_missing"] = bucketed_median_impute(df, "BHK", "Area_Sqft", n_bins=5)
    for col in GROUP_MEDIAN_IMPUTE_COLS:
        df[col], df[f"{col}_was_missing"] = group_median_impute(df, col, "BHK")

    for col in ["Society", "Locality"]:
        df[col] = df[col].fillna("Unknown")
    for col in ["rera_project_status", "rera_project_type", "rera_district"]:
        df[col] = df[col].fillna("Not Matched")

    df["log_price"] = np.log1p(df["Price_INR"])
    df["floor_ratio"] = (df["Floor_Number"] / df["Total_Floors"].replace(0, np.nan)).fillna(0).clip(0, 1)
    df["has_rera_match"] = df["rera_project_name"].notna().astype(int)

    for col in LOW_CARD_CATS:
        df[col] = collapse_to_top_n(df[col].fillna("Unknown"), n=10)

    return df.drop(columns=[c for c in DROP_COLS if c in df.columns])


def build_feature_matrix(cleaned: pd.DataFrame) -> pd.DataFrame:
    """One-hot encoded, leakage-free feature matrix. Price_INR/log_price stay as targets."""
    df = cleaned.drop(columns=[c for c in LEAKAGE_COLS if c in cleaned.columns])
    df = df.drop(columns=[c for c in ["URL"] if c in df.columns])
    return pd.get_dummies(df, columns=LOW_CARD_CATS + ["deal_type"],
                           prefix=LOW_CARD_CATS + ["deal_type"])


def run(listings: pd.DataFrame, rera: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """General-purpose cleaned dataset: keeps deal_type/duplicates as columns
    rather than filtering, so overall row loss vs `listings` stays under
    MAX_DATA_LOSS_PCT. Returns (cleaned_with_leakage_cols_kept, feature_matrix,
    match_report) -- match_report also carries data_loss_pct.
    """
    n_start = len(listings)
    valid = drop_invalid_rows(listings)
    merged, match_report = match_listings_to_rera(valid, rera)
    cleaned = clean_and_engineer(merged)
    features = build_feature_matrix(cleaned)

    n_final = len(cleaned)
    loss_pct = round(100 * (n_start - n_final) / n_start, 2)
    match_report["n_listings_start"] = n_start
    match_report["n_listings_final"] = n_final
    match_report["data_loss_pct"] = loss_pct
    if loss_pct > MAX_DATA_LOSS_PCT:
        raise ValueError(f"data loss {loss_pct}% exceeds the {MAX_DATA_LOSS_PCT}% budget "
                          f"({n_start - n_final:,} of {n_start:,} rows dropped)")

    return cleaned, features, match_report
