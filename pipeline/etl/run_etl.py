"""ETL entrypoint: extract -> transform -> load.

    python3 -m pipeline.etl.run_etl

Writes:
    tsrera/data_analysis/raw/model_cleaned_listings.csv   -- cleaned, engineered,
        leakage columns (Price_Cr, PricePerSqft) kept as reference only.
    tsrera/data_analysis/raw/model_ready_listings.csv     -- one-hot encoded
        feature matrix, leakage-free, ready for a model.
    tsrera/data_analysis/raw/KONU_Real_Estate_Analysis.xlsx -- the Excel report.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .extract import load_listings, load_rera
from .load import save_csv, write_report_workbook
from .report import correlation_with_target, missingness_table, numeric_summary, top_categories
from .transform import MAX_DATA_LOSS_PCT
from .transform import run as run_transform

METHODOLOGY = [
    ("Source", "All_Merged_Updated.csv (nobroker.in/squareyards.com listings) "
               "merged against tsrera's TS RERA project export."),
    ("Row validity filter", "Drops only rows with a missing or non-positive Price_INR or "
                             "Area_Sqft -- no valid target/area means no honest way to use "
                             "or impute the row. ~3.8% of rows."),
    ("Data-loss budget", f"Total row loss vs the raw listings file is held under "
                          f"{MAX_DATA_LOSS_PCT}% -- the ETL raises an error if a change to "
                          f"the pipeline pushes it over. Everything past the validity filter "
                          f"is non-destructive (impute, winsorize, flag) rather than dropped."),
    ("Outlier handling", "Price_INR/Area_Sqft/PricePerSqft are winsorized (capped) to their "
                          "1st-99th percentile, not dropped -- keeps every row while still "
                          "controlling extreme-value skew."),
    ("Deal type", "Sale/Rent/Lease/Unknown derived from the listing URL slug (the source "
                  "Transaction column is not a clean label). Lease is split from Rent "
                  "because a lease listing's price is a deposit (lakhs), not a monthly rent "
                  "-- mixing the two wrecks any average-rent figure."),
    ("Missing-value imputation", "Group-median by BHK for Bathrooms/Balconies/Car_Parking/"
                                  "Floor_Number/Total_Floors/Property_Age_Years -- all scale "
                                  "with unit size, so a flat global median or a blind "
                                  "zero-fill biases the wrong rows in the wrong direction. "
                                  "BHK itself is imputed from an Area_Sqft quantile bucket. "
                                  "Every imputed column carries a companion "
                                  "<column>_was_missing flag so a model can distinguish "
                                  "observed values from imputed ones."),
    ("Categorical normalization", "Spelling/casing/whitespace variants (\"Ready to Move\" / "
                                   "\"Ready to move\" / \"Ready to move Property\") are folded "
                                   "together before collapsing each field to its top 10 "
                                   "categories -- done before, not after, so common values "
                                   "aren't split across near-duplicate labels."),
    ("RERA entity match", "Pincode-blocked fuzzy match (threshold 85) on Society vs RERA "
                           "project name, falling back to a name-only match across all RERA "
                           "projects (threshold 90) with no geographic block. Every row "
                           "carries match_score/match_method for confidence filtering."),
    ("Leakage removal", "Price_Cr and PricePerSqft are both deterministic functions of "
                         "Price_INR (and Area_Sqft) -- excluded from the one-hot feature "
                         "matrix, kept only as reference columns on the cleaned table."),
]

RAW = Path(__file__).resolve().parents[2] / "tsrera" / "data_analysis" / "raw"

NUMERIC_FOR_CORR = [
    "Price_INR", "log_price", "BHK", "Area_Sqft", "Bathrooms", "Balconies",
    "Car_Parking", "Floor_Number", "Total_Floors", "Property_Age_Years",
    "floor_ratio", "has_rera_match", "Latitude", "Longitude",
    "Cement_Price_Rs_per_bag_50kg", "Steel_TMT_Price_Rs_per_tonne",
]

# log_price is a transform of Price_INR itself (the alternate regression
# target), not a predictor -- excluded here so it doesn't top the
# correlate-with-price table the way Price_Cr/PricePerSqft would.
CANDIDATE_FEATURES_FOR_CORR = [c for c in NUMERIC_FOR_CORR if c != "log_price"]


def main():
    print("extract...")
    listings = load_listings()
    rera = load_rera()

    print("transform...")
    cleaned, features, match_report = run_transform(listings, rera)

    print(f"cleaned: {cleaned.shape}, feature matrix: {features.shape}")
    print("match report:", match_report)

    print("building report tables...")
    # The Excel workbook carries the human-readable cleaned table (plain category
    # strings) for reading; the one-hot encoded feature matrix (85+ mostly-boolean
    # columns) is a model-input artifact, not a reading surface -- CSV only.
    sheets = {
        "Methodology": pd.DataFrame(METHODOLOGY, columns=["Step", "Description"]),
        "Cleaned_Listings": cleaned,
        "Missingness_Raw_Listings": missingness_table(listings),
        "Missingness_Cleaned_Listings": missingness_table(cleaned),
        "Numeric_Summary": numeric_summary(cleaned, NUMERIC_FOR_CORR),
        "Correlation_With_Price": correlation_with_target(features, "Price_INR", CANDIDATE_FEATURES_FOR_CORR),
        "Top_Localities": top_categories(cleaned, "Locality"),
        "Top_Promoters": top_categories(cleaned, "rera_promoter_name"),
        "RERA_District_Coverage": top_categories(cleaned, "rera_district"),
    }

    sale = cleaned[cleaned["deal_type"] == "Sale"]
    rent = cleaned[cleaned["deal_type"] == "Rent"]
    overview_stats = {
        "Raw listings (before cleaning)": (match_report["n_listings_start"], "#,##0"),
        "Listings analyzed (cleaned)": (match_report["n_listings_final"], "#,##0"),
        "Data loss vs raw listings": (round(match_report["data_loss_pct"] / 100, 4), "0.00%"),
        "  -- of which Sale": (len(sale), "#,##0"),
        "  -- of which Rent": (len(rent), "#,##0"),
        "  -- of which deal type unclear": (int((cleaned["deal_type"] == "Unknown").sum()), "#,##0"),
        "Average sale price (INR)": (round(sale["Price_INR"].mean()) if len(sale) else None, "#,##0"),
        "Median sale price (INR)": (round(sale["Price_INR"].median()) if len(sale) else None, "#,##0"),
        "Average monthly rent (INR)": (round(rent["Price_INR"].mean()) if len(rent) else None, "#,##0"),
        "Average area (sqft)": (round(cleaned["Area_Sqft"].mean(), 1), "#,##0.0"),
        "Average BHK": (round(cleaned["BHK"].mean(), 2), "0.00"),
        "RERA match rate": (round(cleaned["has_rera_match"].mean(), 4), "0.0%"),
    }

    print(f"\ndata loss: {match_report['data_loss_pct']}% "
          f"({match_report['n_listings_start'] - match_report['n_listings_final']:,} of "
          f"{match_report['n_listings_start']:,} rows) -- within the 5% budget")

    print("load...")
    save_csv(cleaned, RAW / "model_cleaned_listings.csv")
    save_csv(features, RAW / "model_ready_listings.csv")
    write_report_workbook(RAW / "KONU_Real_Estate_Analysis.xlsx", sheets, overview_stats)
    print("done ->", RAW / "KONU_Real_Estate_Analysis.xlsx")


if __name__ == "__main__":
    main()
