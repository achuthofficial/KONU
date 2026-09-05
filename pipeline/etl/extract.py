"""Extract stage: load the raw listings and RERA CSVs with correct dtypes.

pandas' CSV type inference isn't reliable on these files (mixed numeric/text
columns like Car_Parking sometimes get inferred as string), so numeric
columns are coerced explicitly here rather than left to pd.read_csv.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

RAW_DIR = Path(__file__).resolve().parents[2] / "tsrera" / "data_analysis" / "raw"

LISTINGS_NUMERIC_COLS = [
    "Price_INR", "Price_Cr", "PricePerSqft", "BHK", "Area_Sqft", "Bathrooms",
    "Balconies", "Car_Parking", "Floor_Number", "Total_Floors",
    "Property_Age_Years", "Pincode", "Latitude", "Longitude",
    "Cement_Price_Rs_per_bag_50kg", "Steel_TMT_Price_Rs_per_tonne",
    "Year", "Month",
]


def load_listings(path: Path | None = None) -> pd.DataFrame:
    df = pd.read_csv(path or RAW_DIR / "All_Merged_Updated.csv", low_memory=False)
    df.columns = [c.strip().lstrip("﻿") for c in df.columns]
    for col in LISTINGS_NUMERIC_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def load_rera(path: Path | None = None) -> pd.DataFrame:
    df = pd.read_csv(path or RAW_DIR / "projects_from_jsonl.csv", low_memory=False)
    return df
