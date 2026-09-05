"""Probabilistic entity resolution: property listings <-> RERA projects.

Shared by the one-off Drive-dataset merge (merge_datasets.py) and the
scheduled pipeline (pipeline/merge_job.py) -- the matching logic is the
same regardless of where the two input CSVs came from.

There is no shared ID between the two sources, so this links them on
(pincode block +) fuzzy name match between listing `Society` and RERA
`Project Information :: Project Name`:

  Tier 1 (pincode block): listing has a Pincode that appears among RERA
    project pincodes -> fuzzy-match Society against just that pincode's
    project names. Small buckets, cheap, high precision. threshold=85.
  Tier 2 (no usable pincode / no tier-1 hit): fuzzy-match Society against
    the full universe of RERA project names. No geo blocking, so a
    stricter threshold is used to hold precision. threshold=90.

Locality strings are deliberately NOT used as a blocking key: listings use
common neighbourhood names ("Madhapur"), RERA addresses use formal
village/mandal names ("MAVALA MERGED VILLAGE IN ADILABAD MUNICIPALITY") --
see tsrera/data_analysis/output/eda_*.json for the numbers behind this.

Every matched row carries match_score/match_method rather than presenting
fuzzy links as certain -- filter by those columns for higher precision.
"""
from __future__ import annotations

import re

import pandas as pd
from rapidfuzz import fuzz, process

TIER1_THRESHOLD = 85
TIER2_THRESHOLD = 90

RERA_COLS_TO_ATTACH = {
    "token": "rera_token",
    "district": "rera_district",
    "Project Information :: Project Name": "rera_project_name",
    "Project Information :: Project Status": "rera_project_status",
    "Project Information :: Project Type": "rera_project_type",
    "Project Information :: Approved Date": "rera_approved_date",
    "Project Information :: Proposed Date of Completion": "rera_proposed_completion_date",
    "summary.Promoter Name": "rera_promoter_name",
    "Address Details :: Pin Code": "rera_pincode",
}


def normalize_name(s) -> str:
    s = str(s).upper()
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def normalize_pincode(v) -> str | None:
    try:
        f = float(v)
        if pd.isna(f):
            return None
        return str(int(f))
    except (TypeError, ValueError):
        return None


def match_listings_to_rera(
    listings: pd.DataFrame,
    rera: pd.DataFrame,
    society_col: str = "Society",
    pincode_col: str = "Pincode",
    progress_every: int | None = 20000,
) -> tuple[pd.DataFrame, dict]:
    """Attach RERA project columns to `listings` by fuzzy name match.

    Returns (augmented_listings, report). `listings` is not mutated in
    place; the returned frame has RERA_COLS_TO_ATTACH plus match_score and
    match_method appended.
    """
    listings = listings.copy()
    rera = rera.dropna(subset=["Project Information :: Project Name"]).copy()
    rera["_norm_name"] = rera["Project Information :: Project Name"].map(normalize_name)
    rera["_norm_pincode"] = rera["Address Details :: Pin Code"].map(normalize_pincode)

    pincode_buckets: dict[str, list[tuple[int, str]]] = {}
    for idx, pin, name in zip(rera.index, rera["_norm_pincode"], rera["_norm_name"]):
        if pin:
            pincode_buckets.setdefault(pin, []).append((idx, name))

    all_rera_names = rera["_norm_name"].tolist()
    all_rera_idx = rera.index.tolist()

    listings["_norm_society"] = listings[society_col].map(
        lambda s: normalize_name(s) if pd.notna(s) else None)
    listings["_norm_pincode"] = listings[pincode_col].map(normalize_pincode) if pincode_col in listings else None

    match_cache: dict[tuple[str, str | None], dict] = {}

    def resolve(norm_society, norm_pincode) -> dict:
        if not norm_society:
            return {"score": None, "method": "no_society", "rera_idx": None}
        key = (norm_society, norm_pincode)
        if key in match_cache:
            return match_cache[key]

        result = {"score": None, "method": "unmatched", "rera_idx": None}

        if norm_pincode and norm_pincode in pincode_buckets:
            bucket = pincode_buckets[norm_pincode]
            choices = [n for _, n in bucket]
            hit = process.extractOne(norm_society, choices, scorer=fuzz.token_sort_ratio,
                                      score_cutoff=TIER1_THRESHOLD)
            if hit is not None:
                _, score, pos = hit
                result = {"score": score, "method": "pincode_block", "rera_idx": bucket[pos][0]}

        if result["rera_idx"] is None:
            hit = process.extractOne(norm_society, all_rera_names, scorer=fuzz.token_sort_ratio,
                                      score_cutoff=TIER2_THRESHOLD)
            if hit is not None:
                _, score, pos = hit
                result = {"score": score, "method": "name_only", "rera_idx": all_rera_idx[pos]}

        match_cache[key] = result
        return result

    records = []
    for i, (soc, pin) in enumerate(zip(listings["_norm_society"], listings["_norm_pincode"])):
        records.append(resolve(soc, pin))
        if progress_every and (i + 1) % progress_every == 0:
            print(f"  ...{i+1:,}/{len(listings):,} rows resolved")

    match_df = pd.DataFrame(records)
    for src_col, dst_col in RERA_COLS_TO_ATTACH.items():
        vals = rera[src_col] if src_col in rera.columns else pd.Series(index=rera.index, dtype=object)
        listings[dst_col] = match_df["rera_idx"].map(vals)
    listings["match_score"] = match_df["score"]
    listings["match_method"] = match_df["method"]
    listings = listings.drop(columns=["_norm_society", "_norm_pincode"])

    n_total = len(listings)
    n_matched = listings["match_method"].isin(["pincode_block", "name_only"]).sum()
    report = {
        "n_listings": n_total,
        "n_matched": int(n_matched),
        "match_rate_pct": round(100 * n_matched / n_total, 2) if n_total else 0.0,
        "method_counts": listings["match_method"].value_counts().to_dict(),
        "n_unique_rera_projects_matched": int(listings["rera_token"].nunique(dropna=True)),
        "n_unique_rera_projects_total": int(rera["token"].nunique(dropna=True)),
    }
    return listings, report
