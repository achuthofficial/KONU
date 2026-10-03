"""Stage 2a: load the archived multi-site CSV and align it to the shared schema."""
import re

import pandas as pd

from .schema import COLUMNS, LEGACY_CSV

UNKNOWN_SOURCE = "unknown (no URL)"
DOMAIN_RE = re.compile(r"https?://(?:www\.)?([^/\s]+)")


def source_of(url):
    m = DOMAIN_RE.search(str(url))
    return m.group(1).lower() if m else None


def load(path=LEGACY_CSV):
    df = pd.read_csv(path, low_memory=False, encoding="utf-8-sig")
    # One URL carries a stray spreadsheet range ("+A2:AB145"): repair it rather than drop the row.
    df["URL"] = df["URL"].str.replace(r"\+A\d+:[A-Z]+\d+", "", regex=True)
    # ~20k archived rows have no URL, so their site cannot be recovered; keep them, labelled.
    df["Source"] = df["URL"].map(source_of).fillna(UNKNOWN_SOURCE)
    df["Pincode"] = df["Pincode"].astype("Int64").astype("string")
    return df.reindex(columns=COLUMNS)
