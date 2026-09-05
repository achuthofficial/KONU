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

from .clean import collapse_to_top_n, derive_deal_type, filter_percentile_outliers

LOW_CARD_CATS = [
    "Furnishing", "Facing", "Ownership", "Overlooking", "Age_Group",
    "Construction_Status", "rera_project_status", "rera_project_type",
]

LEAKAGE_COLS = ["Price_Cr", "PricePerSqft"]

DROP_COLS = [
    "URL", "_links", "Transaction", "YearMonth", "Year", "Month", "Pincode",
    "Full_Address", "match_score", "match_method", "rera_token",
]


def to_sale_only(listings: pd.DataFrame) -> pd.DataFrame:
    df = listings.copy()
    df["deal_type"] = derive_deal_type(df["URL"])
    df = df[df["deal_type"] == "Sale"].drop_duplicates(subset="URL")
    return df.drop(columns=["deal_type"])


def clean_and_engineer(merged: pd.DataFrame) -> pd.DataFrame:
    df = filter_percentile_outliers(merged, ["Price_INR", "Area_Sqft", "PricePerSqft"])
    df = df.copy()

    for col in ["Balconies", "Car_Parking", "Bathrooms"]:
        df[col] = df[col].fillna(0)
    for col in ["Floor_Number", "Total_Floors", "Property_Age_Years", "BHK"]:
        df[col] = df[col].fillna(df[col].median())
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
    return pd.get_dummies(df, columns=LOW_CARD_CATS, prefix=LOW_CARD_CATS)


def run(listings: pd.DataFrame, rera: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Returns (cleaned_with_leakage_cols_kept, feature_matrix, match_report)."""
    sale = to_sale_only(listings)
    merged, match_report = match_listings_to_rera(sale, rera)
    cleaned = clean_and_engineer(merged)
    features = build_feature_matrix(cleaned)
    return cleaned, features, match_report
