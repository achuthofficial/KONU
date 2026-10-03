"""Canonical project paths, so no module hardcodes its own relative guess."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RAW = ROOT / "data" / "raw"           # source datasets, as received
PROCESSED = ROOT / "data" / "processed"  # pipeline outputs
REPORTS = ROOT / "data" / "reports"    # Excel workbook

for _d in (RAW, PROCESSED, REPORTS):
    _d.mkdir(parents=True, exist_ok=True)
