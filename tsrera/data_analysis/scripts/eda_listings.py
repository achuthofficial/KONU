"""EDA over All_Merged_Updated.csv (nobroker/squareyards property listings).

Writes a JSON summary to data_analysis/output/eda_listings.json and prints a
short human-readable digest to stdout.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

RAW = Path(__file__).resolve().parent.parent / "raw" / "All_Merged_Updated.csv"
OUT = Path(__file__).resolve().parent.parent / "output"
OUT.mkdir(parents=True, exist_ok=True)


def to_native(o):
    if isinstance(o, dict):
        return {k: to_native(v) for k, v in o.items()}
    if isinstance(o, list):
        return [to_native(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return None if np.isnan(o) else float(o)
    if pd.isna(o):
        return None
    return o


def main():
    df = pd.read_csv(RAW, low_memory=False)
    df.columns = [c.strip().lstrip("﻿") for c in df.columns]

    summary = {"n_rows": len(df), "n_cols": len(df.columns)}

    # -- schema / missingness -------------------------------------------
    missing = (df.isna().mean() * 100).round(2).sort_values(ascending=False)
    summary["missing_pct_by_col"] = missing.to_dict()
    summary["dtypes"] = {c: str(t) for c, t in df.dtypes.items()}

    # -- duplicates --------------------------------------------------------
    summary["duplicate_rows"] = int(df.duplicated().sum())
    summary["duplicate_urls"] = int(df["URL"].duplicated().sum()) if "URL" in df else None

    # -- numeric distributions -------------------------------------------
    numeric_cols = ["Price_INR", "Price_Cr", "PricePerSqft", "BHK", "Area_Sqft",
                     "Bathrooms", "Balconies", "Floor_Number", "Total_Floors",
                     "Property_Age_Years", "Latitude", "Longitude",
                     "Cement_Price_Rs_per_bag_50kg", "Steel_TMT_Price_Rs_per_tonne"]
    numeric_cols = [c for c in numeric_cols if c in df.columns]
    for c in numeric_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    desc = df[numeric_cols].describe(percentiles=[.01, .05, .25, .5, .75, .95, .99]).T
    summary["numeric_describe"] = desc.to_dict(orient="index")

    # outliers via IQR on price per sqft and price
    for c in ["PricePerSqft", "Price_INR", "Area_Sqft"]:
        if c not in df.columns:
            continue
        s = df[c].dropna()
        q1, q3 = s.quantile(.25), s.quantile(.75)
        iqr = q3 - q1
        lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        n_out = int(((s < lo) | (s > hi)).sum())
        summary.setdefault("outliers_iqr", {})[c] = {
            "lower_bound": float(lo), "upper_bound": float(hi),
            "n_outliers": n_out, "pct_outliers": round(100 * n_out / len(s), 2),
        }

    # -- categorical breakdowns --------------------------------------------
    cat_cols = ["Locality", "Society", "Furnishing", "Facing", "Ownership",
                "Transaction", "Construction_Status", "Age_Group"]
    for c in cat_cols:
        if c not in df.columns:
            continue
        vc = df[c].value_counts(dropna=True).head(20)
        summary.setdefault("top_categories", {})[c] = vc.to_dict()
        summary.setdefault("n_unique", {})[c] = int(df[c].nunique(dropna=True))

    # -- locality-level price aggregation (top 25 by listing count) ------
    if {"Locality", "PricePerSqft"}.issubset(df.columns):
        g = df.groupby("Locality")["PricePerSqft"].agg(["count", "median", "mean"])
        g = g[g["count"] >= 20].sort_values("count", ascending=False).head(25)
        summary["top_localities_by_pricepersqft"] = g.round(1).to_dict(orient="index")

    # -- BHK distribution --------------------------------------------------
    if "BHK" in df.columns:
        summary["bhk_distribution"] = df["BHK"].value_counts(dropna=True).sort_index().to_dict()

    # -- source site split (from URL) --------------------------------------
    if "URL" in df.columns:
        def site(u):
            if not isinstance(u, str):
                return "unknown"
            if "nobroker" in u:
                return "nobroker"
            if "squareyards" in u:
                return "squareyards"
            return "other"
        df["_site"] = df["URL"].map(site)
        summary["rows_by_source_site"] = df["_site"].value_counts().to_dict()

    # -- transaction type (sale vs rent) proxy via Price_Cr magnitude -----
    if "Transaction" in df.columns:
        summary["transaction_counts"] = df["Transaction"].value_counts(dropna=True).to_dict()

    # -- time coverage -------------------------------------------------
    if "YearMonth" in df.columns:
        ym = df["YearMonth"].dropna().astype(str)
        summary["yearmonth_range"] = {"min": ym.min() if len(ym) else None,
                                        "max": ym.max() if len(ym) else None,
                                        "n_non_null": int(ym.shape[0])}
    if "Year" in df.columns:
        summary["year_counts"] = df["Year"].value_counts(dropna=True).sort_index().to_dict()

    # -- geo sanity (Hyderabad bounding box roughly lat 17-18, lon 78-79) --
    if {"Latitude", "Longitude"}.issubset(df.columns):
        lat_ok = df["Latitude"].between(16.5, 18.5)
        lon_ok = df["Longitude"].between(77.5, 79.5)
        summary["geo_in_hyderabad_bbox_pct"] = round(100 * (lat_ok & lon_ok).mean(), 2)
        summary["geo_missing_pct"] = round(100 * df["Latitude"].isna().mean(), 2)

    with open(OUT / "eda_listings.json", "w") as f:
        json.dump(to_native(summary), f, indent=2, default=str)

    # ---- console digest ----
    print(f"rows={summary['n_rows']:,} cols={summary['n_cols']}")
    print(f"duplicate rows: {summary['duplicate_rows']:,}  duplicate URLs: {summary['duplicate_urls']:,}")
    print("\ntop missingness:")
    for k, v in list(missing.items())[:12]:
        print(f"  {k:35s} {v:5.1f}%")
    print("\nsource site split:", summary.get("rows_by_source_site"))
    print("BHK distribution:", summary.get("bhk_distribution"))
    print("geo in Hyderabad bbox:", summary.get("geo_in_hyderabad_bbox_pct"), "%  missing lat/lon:", summary.get("geo_missing_pct"), "%")
    print("year counts:", summary.get("year_counts"))
    if "PricePerSqft" in summary.get("outliers_iqr", {}):
        print("PricePerSqft outliers:", summary["outliers_iqr"]["PricePerSqft"])
    print(f"\nfull summary written -> {OUT/'eda_listings.json'}")


if __name__ == "__main__":
    main()
