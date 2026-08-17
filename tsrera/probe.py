"""One-off recon: spend a single captcha to learn the result grid's shape,
its columns, and how many pages a dense district actually has.

Run interactively:   python3 tsrera/probe.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tsrera.client import (
    CaptchaRejected,
    Client,
    Options,
    parse_pages,
    parse_results,
    prompt_captcha,
)

OUT = Path(__file__).parent / "_probe"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    c = Client()

    # Hyderabad (25) -- dense enough that pagination should appear if it exists.
    opts = Options(type="Promoter", district=25)

    token = c._token()
    text = prompt_captcha(c, OUT)
    try:
        html = c.search(opts, text, token=token, page=1)
    except CaptchaRejected as e:
        print(f"  -> rejected: {e}\n     re-run and retype (6 chars, case matters).")
        return 1

    dest = OUT / "results_page1.html"
    dest.write_text(html, encoding="utf-8")

    cols, rows = parse_results(html)
    pages = parse_pages(html)

    print(f"\n  saved {len(html)} bytes -> {dest}")
    print(f"  columns ({len(cols)}): {cols}")
    print(f"  rows on page 1: {len(rows)}")
    print(f"  pager offers: {pages}  (max={max(pages) if pages else 'n/a'})")

    if rows:
        print("\n  first row:")
        print(json.dumps(rows[0], indent=4)[:1200])
        (OUT / "sample_rows.json").write_text(
            json.dumps(rows[:5], indent=2), encoding="utf-8"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
