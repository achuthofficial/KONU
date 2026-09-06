"""Extract: load the raw listings and RERA CSVs with correct dtypes."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..paths import RAW

# Coerced explicitly: pandas infers several of these as string because of stray
# text values (e.g. Car_Parking carries "Connected" alongside integers).
NUMERIC_COLS = [
    "Price_INR", "Price_Cr", "PricePerSqft", "BHK", "Area_Sqft", "Bathrooms",
    "Balconies", "Car_Parking", "Floor_Number", "Total_Floors",
    "Property_Age_Years", "Pincode", "Latitude", "Longitude",
    "Cement_Price_Rs_per_bag_50kg", "Steel_TMT_Price_Rs_per_tonne",
    "Year", "Month",
]


def load_listings(path: Path | None = None) -> pd.DataFrame:
    df = pd.read_csv(path or RAW / "All_Merged_Updated.csv", low_memory=False)
    df.columns = [c.strip().lstrip("﻿") for c in df.columns]  # strip BOM from first header
    for col in NUMERIC_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def load_rera(path: Path | None = None) -> pd.DataFrame:
    return pd.read_csv(path or RAW / "projects_from_jsonl.csv", low_memory=False)
