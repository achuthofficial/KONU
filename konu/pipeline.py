"""End-to-end pipeline: crawl -> merge -> pincode enrichment -> ONE final CSV.

    python -m konu.pipeline                      # crawl 100 pages/source, merge, enrich
    python -m konu.pipeline --limit 0            # crawl everything (slow)
    python -m konu.pipeline --skip-crawl         # rebuild from existing data only
"""
import argparse
import sys

import pandas as pd

from . import legacy, pincode
from .crawl import crawl
from .schema import COLUMNS, CRAWLED_CSV, FINAL_CSV
from .sources import LIVE_SOURCES


def build_final(out=FINAL_CSV):
    frames = [legacy.load()]
    if CRAWLED_CSV.exists():
        frames.append(pd.read_csv(CRAWLED_CSV, low_memory=False, dtype={"Pincode": "string"}))
    df = pd.concat([f.reindex(columns=COLUMNS) for f in frames], ignore_index=True)

    before = len(df)
    # URL is not unique (one project page lists many units), so only fully identical rows are duplicates.
    df = df.drop_duplicates(keep="last")
    print(f"merged {before} rows, {before - len(df)} identical duplicates dropped", file=sys.stderr)

    filled_before = df["Pincode"].notna().sum()
    df = pincode.enrich(df)
    print(f"pincode filled: {filled_before} -> {df['Pincode'].notna().sum()} of {len(df)} rows", file=sys.stderr)

    out.parent.mkdir(parents=True, exist_ok=True)
    df[COLUMNS].to_csv(out, index=False)
    print(f"\nwrote {out} ({len(df)} rows x {len(COLUMNS)} columns)\nrows per source:", file=sys.stderr)
    print(df["Source"].value_counts().to_string(), file=sys.stderr)
    return df


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sources", default=",".join(LIVE_SOURCES), help="live sources to crawl (comma separated)")
    ap.add_argument("--limit", type=int, default=100, help="max pages per source this run (0 = unlimited)")
    ap.add_argument("--delay", type=float, default=1.0, help="seconds between requests")
    ap.add_argument("--include-rent", action="store_true", help="RealestateIndia: also crawl rent listings")
    ap.add_argument("--skip-crawl", action="store_true", help="skip live crawling, only merge + enrich")
    args = ap.parse_args(argv)

    if not args.skip_crawl:
        crawl([s.strip() for s in args.sources.split(",")], args.limit, args.delay, args.include_rent)
    build_final()


if __name__ == "__main__":
    main()
