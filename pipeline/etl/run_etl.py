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

from .extract import load_listings, load_rera
from .load import save_csv, write_report_workbook
from .report import correlation_with_target, missingness_table, numeric_summary, top_categories
from .transform import run as run_transform

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
        "Cleaned_Listings": cleaned,
        "Missingness_Raw_Listings": missingness_table(listings),
        "Numeric_Summary": numeric_summary(cleaned, NUMERIC_FOR_CORR),
        "Correlation_With_Price": correlation_with_target(features, "Price_INR", CANDIDATE_FEATURES_FOR_CORR),
        "Top_Localities": top_categories(cleaned, "Locality"),
        "Top_Promoters": top_categories(cleaned, "rera_promoter_name"),
        "RERA_District_Coverage": top_categories(cleaned, "rera_district"),
    }

    overview_stats = {
        "Listings analyzed (sale-only, cleaned)": (len(cleaned), "#,##0"),
        "Average sale price (INR)": (round(cleaned["Price_INR"].mean()), "#,##0"),
        "Median sale price (INR)": (round(cleaned["Price_INR"].median()), "#,##0"),
        "Average area (sqft)": (round(cleaned["Area_Sqft"].mean(), 1), "#,##0.0"),
        "Average BHK": (round(cleaned["BHK"].mean(), 2), "0.00"),
        "RERA match rate": (round(cleaned["has_rera_match"].mean(), 4), "0.0%"),
    }

    print("load...")
    save_csv(cleaned, RAW / "model_cleaned_listings.csv")
    save_csv(features, RAW / "model_ready_listings.csv")
    write_report_workbook(RAW / "KONU_Real_Estate_Analysis.xlsx", sheets, overview_stats)
    print("done ->", RAW / "KONU_Real_Estate_Analysis.xlsx")


if __name__ == "__main__":
    main()
