"""Missing-value imputation.

Group-median, not a flat global fill: Bathrooms/Balconies/Car_Parking/
Floor_Number/Total_Floors/Property_Age_Years all scale with unit size, so
imputing a missing Bathrooms with 0 (or with the same global median
regardless of whether the unit is a 1BHK or a 5BHK) systematically biases
the wrong rows in the wrong direction. Grouping by BHK -- rarely missing,
and the single strongest predictor of all of these -- fixes that.

Every imputed column gets a companion `<col>_was_missing` flag. Missingness
here isn't necessarily random (a listing missing Car_Parking may genuinely
have none reported for a reason), so a model should be able to tell an
imputed value from an observed one rather than treating them identically.
"""
from __future__ import annotations

import pandas as pd


def group_median_impute(df: pd.DataFrame, col: str, group_col: str) -> tuple[pd.Series, pd.Series]:
    was_missing = df[col].isna()
    group_median = df.groupby(group_col)[col].transform("median")
    filled = df[col].fillna(group_median).fillna(df[col].median())
    return filled, was_missing


def bucketed_median_impute(df: pd.DataFrame, col: str, bucket_on: str, n_bins: int = 5) -> tuple[pd.Series, pd.Series]:
    """Like group_median_impute, but groups by quantile buckets of a continuous
    column (used for BHK, imputed from Area_Sqft buckets rather than a group
    of itself).
    """
    was_missing = df[col].isna()
    buckets = pd.qcut(df[bucket_on], q=n_bins, duplicates="drop")
    group_median = df.groupby(buckets, observed=True)[col].transform("median")
    filled = df[col].fillna(group_median).fillna(df[col].median())
    return filled.round(), was_missing
