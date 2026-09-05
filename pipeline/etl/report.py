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


def correlation_with_target(df: pd.DataFrame, target: str, numeric_cols: list[str]) -> pd.DataFrame:
    cols = [c for c in numeric_cols if c in df.columns and c != target]
    corr = df[cols + [target]].corr(numeric_only=True)[target].drop(target)
    return corr.sort_values(key=abs, ascending=False).rename("correlation").reset_index().rename(
        columns={"index": "feature"})
