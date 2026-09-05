"""Cleaning primitives used by the transform stage.

normalize_category folds spelling/casing/whitespace variants of the same
category together (e.g. "Ready to Move" / "Ready to move" / "Ready to move
Property" all become one value) before top-N collapsing runs -- otherwise
the variants split a category's count across several labels and a genuinely
common value can miss the top-N cut, and the one-hot columns downstream
carry duplicate categories.
"""
from __future__ import annotations

import re

import pandas as pd

_TRAILING_NOISE = re.compile(r"\s*(property|properties)\s*$", re.IGNORECASE)


def normalize_category(value) -> str | None:
    if pd.isna(value):
        return None
    s = str(value).strip()
    s = _TRAILING_NOISE.sub("", s).strip()
    s = re.sub(r"[\s\-]+", " ", s)
    return s.title() if s else None


def collapse_to_top_n(series: pd.Series, n: int = 10, other_label: str = "Other") -> pd.Series:
    normalized = series.map(normalize_category)
    top = normalized.value_counts().head(n).index
    return normalized.where(normalized.isin(top), other_label)


def derive_deal_type(url: pd.Series) -> pd.Series:
    u = url.astype(str).str.lower()
    is_rent = u.str.contains("for-rent|-rent-|for-lease", regex=True)
    is_sale = u.str.contains("for-sale|resale|-sale-", regex=True) & ~is_rent
    return pd.Series("Unknown", index=url.index).mask(is_sale, "Sale").mask(is_rent, "Rent")


def filter_percentile_outliers(df: pd.DataFrame, cols: list[str], lo_q=0.01, hi_q=0.99) -> pd.DataFrame:
    mask = pd.Series(True, index=df.index)
    for col in cols:
        lo, hi = df[col].quantile([lo_q, hi_q])
        mask &= df[col].between(lo, hi)
    return df[mask]
