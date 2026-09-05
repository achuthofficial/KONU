"""EDA over projects_from_jsonl.csv (TS RERA registered projects, flattened).

Writes a JSON summary to data_analysis/output/eda_rera.json and prints a
short human-readable digest to stdout.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

RAW = Path(__file__).resolve().parent.parent / "raw" / "projects_from_jsonl.csv"
OUT = Path(__file__).resolve().parent.parent / "output"
OUT.mkdir(parents=True, exist_ok=True)


def to_native(o):
    if isinstance(o, dict):
        return {k: to_native(v) for k, v in o.items()}
    if isinstance(o, list):
        return [to_native(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return None if np.isnan(o) else float(o)
    if pd.isna(o):
        return None
    return o


def main():
    df = pd.read_csv(RAW, low_memory=False)

    summary = {"n_rows": len(df), "n_cols": len(df.columns)}

    missing = (df.isna().mean() * 100).round(2).sort_values(ascending=False)
    # only the least-sparse 40 columns are interesting -- the rest are
    # section fields that only a handful of projects filled in.
    summary["least_missing_cols"] = missing.tail(40).to_dict()
    summary["most_missing_cols_sample"] = missing.head(20).to_dict()
    summary["duplicate_rows"] = int(df.duplicated().sum())
    summary["duplicate_tokens"] = int(df["token"].duplicated().sum()) if "token" in df else None

    # -- district coverage --------------------------------------------
    if "district" in df.columns:
        summary["projects_by_district"] = df["district"].value_counts(dropna=True).to_dict()
        summary["n_districts"] = int(df["district"].nunique(dropna=True))

    # -- project status / type ------------------------------------------
    status_col = "Project Information :: Project Status"
    if status_col in df.columns:
        summary["project_status_counts"] = df[status_col].value_counts(dropna=True).to_dict()
    type_col = "Project Information :: Project Type"
    if type_col in df.columns:
        summary["project_type_counts"] = df[type_col].value_counts(dropna=True).to_dict()

    # -- promoter concentration -------------------------------------------
    promoter_col = "summary.Promoter Name"
    if promoter_col in df.columns:
        vc = df[promoter_col].value_counts(dropna=True)
        summary["n_unique_promoters"] = int(vc.shape[0])
        summary["top_25_promoters_by_project_count"] = vc.head(25).to_dict()

    # -- approval dates -> year trend -------------------------------------
    approved_col = "Project Information :: Approved Date"
    if approved_col in df.columns:
        dt = pd.to_datetime(df[approved_col], errors="coerce", dayfirst=True)
        summary["approved_year_counts"] = dt.dt.year.value_counts(dropna=True).sort_index().to_dict()
        summary["approved_date_range"] = {
            "min": str(dt.min()) if dt.notna().any() else None,
            "max": str(dt.max()) if dt.notna().any() else None,
        }

    # -- locality / pincode fields (candidate merge keys) ------------------
    for col in ["Address Details :: Locality", "Address Details :: Locality :",
                "Address Details :: Pin Code", "Address Details :: Mandal",
                "Address Details :: District", "Address Details :: District :"]:
        if col in df.columns:
            summary.setdefault("candidate_merge_key_fill_pct", {})[col] = round(
                100 * df[col].notna().mean(), 2)
            summary.setdefault("candidate_merge_key_nunique", {})[col] = int(df[col].nunique(dropna=True))

    # -- project name field for fuzzy-name matching ------------------------
    name_col = "Project Information :: Project Name"
    if name_col in df.columns:
        summary["project_name_fill_pct"] = round(100 * df[name_col].notna().mean(), 2)
        summary["project_name_nunique"] = int(df[name_col].nunique(dropna=True))
        summary["project_name_sample"] = df[name_col].dropna().head(15).tolist()

    with open(OUT / "eda_rera.json", "w") as f:
        json.dump(to_native(summary), f, indent=2, default=str)

    print(f"rows={summary['n_rows']:,} cols={summary['n_cols']}")
    print(f"duplicate rows: {summary['duplicate_rows']:,}  duplicate tokens: {summary['duplicate_tokens']}")
    print("\nprojects by district (top 15):")
    for k, v in list(summary.get("projects_by_district", {}).items())[:15]:
        print(f"  {k:20s} {v}")
    print("\nproject status:", summary.get("project_status_counts"))
    print("project type:", summary.get("project_type_counts"))
    print("n unique promoters:", summary.get("n_unique_promoters"))
    print("\ncandidate merge-key fill %:", summary.get("candidate_merge_key_fill_pct"))
    print("candidate merge-key nunique:", summary.get("candidate_merge_key_nunique"))
    print("\nproject name fill %:", summary.get("project_name_fill_pct"), " nunique:", summary.get("project_name_nunique"))
    print("sample project names:", summary.get("project_name_sample"))
    print(f"\nfull summary written -> {OUT/'eda_rera.json'}")


if __name__ == "__main__":
    main()
