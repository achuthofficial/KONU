"""End-to-end TS RERA extractor.

IMPORTANT design note: each row's detail token is **time-limited** -- it expires
minutes after the listing page is loaded. So harvesting all listings first and
enriching later does NOT work (early tokens die before enrich reaches them).
This tool therefore enriches every project INLINE, the moment its page is read,
while the token is seconds old.

  scrape  -- for chosen districts, page through the listing (captcha per fresh
             search; paging within a district is captcha-free) and immediately
             fetch + parse each project's full detail. Writes data/details.jsonl.
             Fully resumable per project token.

  export  -- flatten details.jsonl into data/projects.csv.

Usage:
  python3 tsrera/run.py scrape --districts 25           # Hyderabad
  python3 tsrera/run.py scrape --districts all          # every district
  python3 tsrera/run.py export
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tsrera.client import (
    CaptchaRejected,
    Client,
    Options,
    TokenExpired,
    parse_results,
    parse_state,
    prompt_captcha,
    row_tokens,
)
from tsrera.detail_parser import parse_detail

DATA = Path(__file__).parent / "data"
DETAILS = DATA / "details.jsonl"
PROGRESS = DATA / "progress.json"
WORK = DATA / "_captcha"


def _load_progress() -> dict:
    if PROGRESS.exists():
        return json.loads(PROGRESS.read_text())
    return {"districts_done": []}


def _save_progress(p: dict) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    PROGRESS.write_text(json.dumps(p, indent=2))


def _append(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def _done_tokens() -> set[str]:
    if not DETAILS.exists():
        return set()
    out = set()
    for line in DETAILS.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rec = json.loads(line)
            if rec.get("detail", {}).get("sections"):  # only count real successes
                out.add(rec["token"])
    return out


def _solve_and(fn, client: Client):
    """Call fn(captcha_text) -> html, retrying until accepted."""
    while True:
        text = prompt_captcha(client, WORK)
        try:
            return fn(text)
        except CaptchaRejected as e:
            print(f"    captcha rejected ({e}); try again.")


def _enrich_page(c: Client, html: str, did: int, dname: str, page: int,
                 done: set[str], expired: list) -> int:
    """Fetch + parse detail for every row on a freshly-loaded listing page."""
    _cols, rows = parse_results(html)
    toks = row_tokens(html)
    n_ok = 0
    for i, row in enumerate(rows):
        tok = toks[i] if i < len(toks) else None
        summary = {k: v for k, v in row.items() if not k.startswith("_")}
        name = summary.get("Project Name", "?")[:40]
        if not tok:
            continue
        if tok in done:
            n_ok += 1
            continue
        try:
            detail = parse_detail(c.detail(tok))
        except TokenExpired:
            expired.append({"district": dname, "page": page, "summary": summary})
            print(f"      ! token expired before fetch: {name}")
            continue
        except Exception as e:
            _append(DETAILS, {"district": dname, "district_id": did, "token": tok,
                              "summary": summary, "error": str(e)})
            print(f"      ! error {name}: {e}")
            continue
        _append(DETAILS, {"district": dname, "district_id": did, "token": tok,
                          "summary": summary, "detail": detail})
        done.add(tok)
        n_ok += 1
    return n_ok


def scrape(district_ids: list[int]) -> None:
    c = Client()
    prog = _load_progress()
    done = _done_tokens()
    name_by_id = {d["id"]: d["name"] for d in c.districts()}
    print(f"resuming: {len(done)} projects already enriched\n")

    for did in district_ids:
        if did in prog["districts_done"]:
            print(f"[{did} {name_by_id.get(did,'')}] already complete, skipping")
            continue
        dname = name_by_id.get(did, str(did))
        opts = Options(type="Promoter", district=did)
        print(f"\n[{did} {dname}] search")

        while True:
            token = c._token()
            html = _solve_and(lambda t: c.search(opts, t, token=token, page=1), c)
            state = parse_state(html)
            if state["TotalRecords"] > 0:
                break
            # District search returning zero almost always means the captcha was
            # silently rejected. Save the response and re-prompt.
            dbg = DATA / "_debug_search.html"
            dbg.write_text(html, encoding="utf-8")
            print("    0 records -- likely a rejected captcha. "
                  f"(saved response to {dbg}); retrying.")
        total_pages = state["TotalPages"] or 1
        print(f"    {state['TotalRecords']} records / {total_pages} pages")

        expired: list = []
        page = 1
        while True:
            t0 = time.monotonic()
            ok = _enrich_page(c, html, did, dname, page, done, expired)
            print(f"    page {page}/{total_pages}: {ok} enriched "
                  f"({time.monotonic()-t0:.0f}s, {len(done)} total)")
            if page >= total_pages:
                break
            page += 1
            state["CurrentPage"] = page - 1
            try:
                html = c.paginate(opts, state, captcha_text="", command="Next")
            except CaptchaRejected:
                html = _solve_and(
                    lambda t: c.paginate(opts, state, captcha_text=t, command="Next"), c)
            state = parse_state(html) or state
            state["CurrentPage"] = page

        if expired:
            _append(DATA / "expired.jsonl", {"district": dname, "items": expired})
            print(f"    note: {len(expired)} tokens expired mid-run (logged)")
        prog["districts_done"].append(did)
        _save_progress(prog)
        print(f"[{did} {dname}] done")


def export(district: str | None = None) -> None:
    import csv

    recs = [json.loads(l) for l in DETAILS.read_text(encoding="utf-8").splitlines() if l.strip()]
    recs = [r for r in recs if r.get("detail", {}).get("sections")]
    available = sorted({r.get("district", "?") for r in recs})
    if district:
        want = district.strip().lower()
        recs = [r for r in recs if str(r.get("district", "")).lower() == want]
        if not recs:
            print(f"no enriched records for district {district!r}. available: {available}")
            return
    flat, keys = [], []
    for r in recs:
        row = {"district": r.get("district"), "token": r.get("token")}
        row.update({f"summary.{k}": v for k, v in (r.get("summary") or {}).items()})
        for sec, pairs in (r["detail"].get("sections") or {}).items():
            for k, v in pairs.items():
                row[f"{sec} :: {k}"] = v
        for k in row:
            if k not in keys:
                keys.append(k)
        flat.append(row)

    slug = "".join(ch if ch.isalnum() else "_" for ch in district.lower()) if district else "all"
    out = DATA / f"projects_{slug}.csv"
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(flat)
    print(f"wrote {len(flat)} projects x {len(keys)} columns -> {out}")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scrape")
    s.add_argument("--districts", default="all",
                   help="'all', or comma-separated district ids e.g. 25,1,9")
    e = sub.add_parser("export")
    e.add_argument("--district", default=None,
                   help="export just this district by name, e.g. --district Hyderabad")
    args = ap.parse_args()

    if args.cmd == "scrape":
        if args.districts == "all":
            ids = [d["id"] for d in Client().districts()]
        else:
            ids = [int(x) for x in args.districts.split(",") if x.strip()]
        scrape(ids)
    elif args.cmd == "export":
        export(args.district)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
