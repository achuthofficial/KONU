"""Cleaning primitives: category normalization, deal-type parsing, outlier capping."""
from __future__ import annotations

import re

import pandas as pd

_TRAILING_NOISE = re.compile(r"\s*(property|properties)\s*$", re.IGNORECASE)


def normalize_category(value) -> str | None:
    """Fold casing/spacing/suffix variants together ("Ready to move Property" -> "Ready To Move")."""
    if pd.isna(value):
        return None
    s = _TRAILING_NOISE.sub("", str(value).strip()).strip()
    s = re.sub(r"[\s\-]+", " ", s)
    return s.title() if s else None


def collapse_to_top_n(series: pd.Series, n: int = 10, other_label: str = "Other") -> pd.Series:
    """Keep the n most common categories, fold the rest into "Other"."""
    # Normalize first, or spelling variants split one category's count across several labels.
    normalized = series.map(normalize_category)
    top = normalized.value_counts().head(n).index
    return normalized.where(normalized.isin(top), other_label)


def derive_deal_type(url: pd.Series) -> pd.Series:
    """Sale / Rent / Lease / Unknown from the URL slug (the Transaction column isn't a clean label)."""
    u = url.astype(str).str.lower()
    # Lease is separate from Rent: a lease price is a deposit in lakhs, not a monthly rent.
    is_lease = u.str.contains("for-lease", regex=True)
    is_rent = u.str.contains("for-rent|-rent-", regex=True) & ~is_lease
    is_sale = u.str.contains("for-sale|resale|-sale-", regex=True) & ~is_rent & ~is_lease
    out = pd.Series("Unknown", index=url.index)
    return out.mask(is_sale, "Sale").mask(is_rent, "Rent").mask(is_lease, "Lease")


def filter_percentile_outliers(df: pd.DataFrame, cols: list[str], lo_q=0.01, hi_q=0.99) -> pd.DataFrame:
    """Drop rows outside the percentile band. Row-destructive -- prefer winsorize under a loss budget."""
    mask = pd.Series(True, index=df.index)
    for col in cols:
        lo, hi = df[col].quantile([lo_q, hi_q])
        mask &= df[col].between(lo, hi)
    return df[mask]


def winsorize(df: pd.DataFrame, cols: list[str], lo_q=0.01, hi_q=0.99) -> pd.DataFrame:
    """Cap values to the percentile band, keeping every row."""
    df = df.copy()
    for col in cols:
        lo, hi = df[col].quantile([lo_q, hi_q])
        df[col] = df[col].clip(lo, hi)
    return df


def winsorize_by_group(df: pd.DataFrame, cols: list[str], group_col: str,
                        lo_q=0.01, hi_q=0.99) -> pd.DataFrame:
    """Cap within each group separately.

    Required for prices: sale, rent and lease share one Price_INR column three orders of
    magnitude apart, so a global 1st-percentile floor (~Rs 27,000) sits above the median
    rent and would inflate ~46% of rent rows up to it.
    """
    df = df.copy()
    for col in cols:
        lo = df.groupby(group_col)[col].transform(lambda s: s.quantile(lo_q))
        hi = df.groupby(group_col)[col].transform(lambda s: s.quantile(hi_q))
        df[col] = df[col].clip(lo, hi)
    return df
