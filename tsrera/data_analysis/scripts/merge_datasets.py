"""Entity-resolve property listings against TS RERA registered projects.

There is no shared ID between the two sources -- listings come from
nobroker/squareyards scrapes, RERA projects come from the government
registry. So this links them probabilistically on (pincode block +) fuzzy
name match between listing `Society` and RERA `Project Information ::
Project Name`, and is explicit about match confidence rather than presenting
fuzzy links as certain.

Strategy (see tsrera/data_analysis/output/eda_listings.json /
eda_rera.json for the numbers behind these choices):
  - Pincode overlap is real: 21,357/24,366 listing rows with a pincode carry
    one that RERA also has -- so pincode is a reliable, cheap block.
  - Locality strings are NOT directly comparable: listings use common
    neighbourhood names ("Madhapur"), RERA addresses use formal
    village/mandal names ("MAVALA MERGED VILLAGE IN ADILABAD MUNICIPALITY").
    So locality is not used as a blocking key -- only pincode is.

  Tier 1 (pincode block): listing has a Pincode that appears among RERA
    project pincodes -> fuzzy-match Society against just that pincode's
    project names. Small buckets, cheap, high precision. threshold=85.
  Tier 2 (no usable pincode / no tier-1 hit): fuzzy-match Society against
    the full universe of ~10.5k unique RERA project names. No geo blocking,
    so a stricter threshold is used to hold precision. threshold=90.

Matching is memoized per unique normalized Society string (there are ~10.7k
unique Society values across 93k rows), so the expensive fuzzy matching runs
once per distinct name, not once per row.

Outputs:
  tsrera/data_analysis/raw/merged_listings_rera.csv  -- every listing row,
    plus matched RERA columns (null if unmatched) + match_score + match_method.
  tsrera/data_analysis/output/merge_report.json -- coverage / score summary.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd
from rapidfuzz import fuzz, process

RAW = Path(__file__).resolve().parent.parent / "raw"
OUT = Path(__file__).resolve().parent.parent / "output"
OUT.mkdir(parents=True, exist_ok=True)

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


def normalize_name(s: str) -> str:
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


def main():
    listings = pd.read_csv(RAW / "All_Merged_Updated.csv", low_memory=False)
    listings.columns = [c.strip().lstrip("﻿") for c in listings.columns]
    rera = pd.read_csv(RAW / "projects_from_jsonl.csv", low_memory=False)

    rera = rera.dropna(subset=["Project Information :: Project Name"]).copy()
    rera["_norm_name"] = rera["Project Information :: Project Name"].map(normalize_name)
    rera["_norm_pincode"] = rera["Address Details :: Pin Code"].map(normalize_pincode)

    # pincode -> list of (row_idx, normalized name)
    pincode_buckets: dict[str, list[tuple[int, str]]] = {}
    for idx, pin, name in zip(rera.index, rera["_norm_pincode"], rera["_norm_name"]):
        if pin:
            pincode_buckets.setdefault(pin, []).append((idx, name))

    all_rera_names = rera["_norm_name"].tolist()
    all_rera_idx = rera.index.tolist()

    listings["_norm_society"] = listings["Society"].map(
        lambda s: normalize_name(s) if pd.notna(s) else None)
    listings["_norm_pincode"] = listings["Pincode"].map(normalize_pincode)

    # unique (society, pincode) name -> match memoization
    match_cache: dict[tuple[str, str | None], dict] = {}

    def resolve(norm_society: str | None, norm_pincode: str | None) -> dict:
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

    print(f"resolving matches for {listings['_norm_society'].nunique(dropna=True):,} unique society names "
          f"against {rera['_norm_name'].nunique():,} unique RERA project names...")

    records = []
    for i, (soc, pin) in enumerate(zip(listings["_norm_society"], listings["_norm_pincode"])):
        records.append(resolve(soc, pin))
        if (i + 1) % 20000 == 0:
            print(f"  ...{i+1:,}/{len(listings):,} rows resolved")

    match_df = pd.DataFrame(records)
    for src_col, dst_col in RERA_COLS_TO_ATTACH.items():
        vals = rera[src_col] if src_col in rera.columns else pd.Series(index=rera.index, dtype=object)
        listings[dst_col] = match_df["rera_idx"].map(vals)
    listings["match_score"] = match_df["score"]
    listings["match_method"] = match_df["method"]

    listings = listings.drop(columns=["_norm_society", "_norm_pincode"])
    out_path = RAW / "merged_listings_rera.csv"
    listings.to_csv(out_path, index=False)

    n_total = len(listings)
    n_matched = listings["match_method"].isin(["pincode_block", "name_only"]).sum()
    report = {
        "n_listings": n_total,
        "n_matched": int(n_matched),
        "match_rate_pct": round(100 * n_matched / n_total, 2),
        "method_counts": listings["match_method"].value_counts().to_dict(),
        "score_describe_by_method": {
            m: listings.loc[listings["match_method"] == m, "match_score"].describe().round(1).to_dict()
            for m in ["pincode_block", "name_only"]
        },
        "n_unique_rera_projects_matched": int(listings["rera_token"].nunique(dropna=True)),
        "n_unique_rera_projects_total": int(rera["token"].nunique(dropna=True)),
    }
    with open(OUT / "merge_report.json", "w") as f:
        json.dump(report, f, indent=2, default=str)

    print(f"\nmatched {n_matched:,}/{n_total:,} listings ({report['match_rate_pct']}%)")
    print("by method:", report["method_counts"])
    print(f"covers {report['n_unique_rera_projects_matched']:,}/{report['n_unique_rera_projects_total']:,} distinct RERA projects")
    print(f"\nmerged dataset -> {out_path}")
    print(f"report -> {OUT/'merge_report.json'}")


if __name__ == "__main__":
    main()
