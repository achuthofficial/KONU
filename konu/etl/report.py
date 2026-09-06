"""Summary tables used by the Excel report and the in-depth EDA notebook."""
from __future__ import annotations

import pandas as pd


def missingness_table(df: pd.DataFrame) -> pd.DataFrame:
    m = (df.isna().mean() * 100).round(2).sort_values(ascending=False)
    return m.rename("missing_pct").reset_index().rename(columns={"index": "column"})


def numeric_summary(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    cols = [c for c in cols if c in df.columns]
    return df[cols].describe(percentiles=[.01, .05, .25, .5, .75, .95, .99]).T.reset_index().rename(
        columns={"index": "column"})


def top_categories(df: pd.DataFrame, col: str, n: int = 15) -> pd.DataFrame:
    vc = df[col].value_counts(dropna=True).head(n)
    return vc.rename("count").reset_index().rename(columns={"index": col})


def imputation_summary(cleaned: pd.DataFrame) -> pd.DataFrame:
    """One row per imputed column: how much was filled in, and by what method."""
    methods = {
        "BHK": "Median within Area_Sqft quantile bucket",
        "Bathrooms": "Median within BHK group",
        "Balconies": "Median within BHK group",
        "Car_Parking": "Median within BHK group",
        "Floor_Number": "Median within BHK group",
        "Total_Floors": "Median within BHK group",
        "Property_Age_Years": "Median within BHK group",
        "Pincode": "Society mode -> spatial KNN on lat/long -> locality mode (~68% accurate on held-out observed pincodes)",
        "geo": "Latitude/Longitude from locality centroid, then pincode centroid",
        "Cement_Price_Rs_per_bag_50kg": "Median within same YearMonth, then same Year",
        "Steel_TMT_Price_Rs_per_tonne": "Median within same YearMonth, then same Year",
    }
    rows = []
    for col, method in methods.items():
        flag = "geo_was_missing" if col == "geo" else f"{col}_was_missing"
        if flag not in cleaned.columns:
            continue
        n = int(cleaned[flag].sum())
        rows.append({
            "column": col,
            "rows_imputed": n,
            "pct_imputed": round(100 * n / len(cleaned), 2),
            "method": method,
        })
    return pd.DataFrame(rows).sort_values("pct_imputed", ascending=False)


def correlation_with_target(df: pd.DataFrame, target: str, numeric_cols: list[str]) -> pd.DataFrame:
    cols = [c for c in numeric_cols if c in df.columns and c != target]
    corr = df[cols + [target]].corr(numeric_only=True)[target].drop(target)
    return corr.sort_values(key=abs, ascending=False).rename("correlation").reset_index().rename(
        columns={"index": "feature"})
