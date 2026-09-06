"""ETL entrypoint: extract -> transform -> load.

    python3 -m konu.etl.run_etl

Writes:
    data/processed/model_cleaned_listings.csv   -- cleaned, engineered,
        leakage columns (Price_Cr, PricePerSqft) kept as reference only.
    data/processed/model_ready_listings.csv     -- one-hot encoded
        feature matrix, leakage-free, ready for a model.
    data/processed/KONU_Real_Estate_Analysis.xlsx -- the Excel report.
"""
from __future__ import annotations

import pandas as pd

from ..paths import PROCESSED, REPORTS
from .extract import load_listings, load_rera
from .load import save_csv, write_report_workbook
from .report import (correlation_with_target, imputation_summary, missingness_table,
                      numeric_summary, top_categories)
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
                          "controlling extreme-value skew. Capping is done WITHIN each deal "
                          "type, because sale prices, monthly rents and lease deposits share "
                          "one Price_INR column at three different orders of magnitude: a "
                          "single global 1st-percentile floor sits at ~Rs 27,000, above the "
                          "median monthly rent, and would silently inflate ~46% of rent rows "
                          "up to that floor rather than leaving them untouched."),
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
                                  "observed values from imputed ones. See the "
                                  "Imputation_Summary sheet for per-column coverage."),
    ("Pincode imputation", "Only 26.8% of rows carry an observed pincode. Imputed in layers: "
                            "society mode (societies are 79% single-pincode), then a spatial "
                            "KNN on latitude/longitude, then locality mode. Measured against "
                            "held-out observed pincodes this is ~68% accurate at ~99.8% "
                            "coverage -- good enough to use as a coarse geographic feature, "
                            "NOT as a verified address. Locality mode alone scored only ~55% "
                            "(a locality spans a median of 7 pincodes). Pincode_was_missing "
                            "and Pincode_impute_source record which rows were imputed and how. "
                            "4.9% of rows stay unimputed (source='unimputed'): they have no "
                            "society, no coordinates and no locality with any observed pincode "
                            "-- there is no signal there to impute from, so they are left null "
                            "rather than filled with a guess."),
    ("Latitude/Longitude", "Filled from the locality's own centroid, then the pincode centroid "
                            "(6.3% of rows). Imputed before nothing else depends on them: the "
                            "pincode KNN is trained only on observed coordinates."),
    ("PricePerSqft", "Recomputed as Price_INR / Area_Sqft rather than imputed -- it is "
                      "definitionally that ratio, and both inputs are guaranteed present by "
                      "the validity filter. This also repairs rows whose source value was "
                      "missing or inconsistent."),
    ("Commodity prices", "Cement and steel prices are macro time series, so missing values are "
                          "filled with the median for the same YearMonth (then the same Year) "
                          "-- the right neighbour is the same month, not a similar property."),
    ("Deliberately not imputed", "rera_project_name / rera_promoter_name / rera_approved_date / "
                                  "rera_proposed_completion_date / rera_pincode are only "
                                  "populated where a listing actually matched a RERA project. "
                                  "Inventing a promoter name or approval date for an unmatched "
                                  "listing would fabricate a government record, not impute a "
                                  "measurement -- has_rera_match carries that signal instead."),
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
    rental = cleaned[cleaned["deal_type"].isin(["Rent", "Lease"])]

    sheets = {
        "Methodology": pd.DataFrame(METHODOLOGY, columns=["Step", "Description"]),
        "Cleaned_Listings": cleaned,
        "Rental_Listings": rental,
        "Imputation_Summary": imputation_summary(cleaned),
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
        "  -- of which Lease": (int((cleaned["deal_type"] == "Lease").sum()), "#,##0"),
        "  -- of which deal type unclear": (int((cleaned["deal_type"] == "Unknown").sum()), "#,##0"),
        "Average sale price (INR)": (round(sale["Price_INR"].mean()) if len(sale) else None, "#,##0"),
        "Median sale price (INR)": (round(sale["Price_INR"].median()) if len(sale) else None, "#,##0"),
        "Median monthly rent (INR)": (round(rent["Price_INR"].median()) if len(rent) else None, "#,##0"),
        "Average area (sqft)": (round(cleaned["Area_Sqft"].mean(), 1), "#,##0.0"),
        "Average BHK": (round(cleaned["BHK"].mean(), 2), "0.00"),
        "RERA match rate": (round(cleaned["has_rera_match"].mean(), 4), "0.0%"),
        "Pincode observed (not imputed)": (round(1 - cleaned["Pincode_was_missing"].mean(), 4), "0.0%"),
    }

    print(f"\ndata loss: {match_report['data_loss_pct']}% "
          f"({match_report['n_listings_start'] - match_report['n_listings_final']:,} of "
          f"{match_report['n_listings_start']:,} rows) -- within the {MAX_DATA_LOSS_PCT}% budget")
    print(f"rental subset (Rent+Lease): {len(rental):,} rows")

    print("load...")
    save_csv(cleaned, PROCESSED / "model_cleaned_listings.csv")
    save_csv(features, PROCESSED / "model_ready_listings.csv")
    save_csv(rental, PROCESSED / "rental_listings.csv")
    save_csv(cleaned[cleaned["deal_type"] == "Sale"], PROCESSED / "sale_listings.csv")
    write_report_workbook(REPORTS / "KONU_Real_Estate_Analysis.xlsx", sheets, overview_stats)
    print("done ->", REPORTS / "KONU_Real_Estate_Analysis.xlsx")


if __name__ == "__main__":
    main()
