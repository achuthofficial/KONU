# KONU: Hyderabad property data pipeline

One command collects property listings from several websites, merges them with the
archived dataset, fills in missing pincodes from coordinates, and writes
**everything to a single CSV**:

    data/output/properties_all_sources.csv

## Sources

| Site | Coverage | How |
|---|---|---|
| nobroker.in | owner listings: flats, houses, villas, plots (sale; rent with `--include-rent`) | live crawl: sitemap index pages -> detail pages |
| magicbricks.com | Hyderabad project pages (price range, coordinates, pincode, status, units, rating) | live crawl: `pdp_Hyderabad` sitemap |
| squareyards.com | Hyderabad resale listings (via the city listing index) and new-project pages (via project sitemaps) | live crawl |
| realestateindia.com | resale/new flats, houses, villas, plots | live crawl: sitemaps |
| proptiger.com | Hyderabad new projects | live crawl: sitemaps |
| 99acres.com | archived rows only | **no crawler**: the site returns "Access Denied" to automated requests, even for `robots.txt` |

The archived dataset (`data/raw/legacy_listings.csv`: NoBroker, MagicBricks, SquareYards, 99acres) is merged in too.
Archived rows with no URL (about 17k) cannot be traced to a site; they are kept as `Source = unknown (no URL)`.
Filter on the `Source` column to pick any subset. Housing.com and Makaan are also bot-protected and are not crawled.

Every crawler honours `robots.txt`, rate-limits to one request per `--delay` seconds per site, and does not try to bypass bot protection.

## Setup

    python3 -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt

## Run once

    python -m konu.pipeline                  # crawl 100 new pages per site, merge, enrich -> final CSV
    python -m konu.pipeline --limit 0        # crawl everything (see "How long a full crawl takes")
    python -m konu.pipeline --skip-crawl     # rebuild the final CSV from existing data (about 15 s)

Options: `--sources nobroker,magicbricks,...`, `--limit N`, `--delay SECONDS`, `--include-rent`.
Sites are crawled in parallel (one thread and rate limiter per site). Crawling is resumable:
visited pages are tracked per site in `data/interim/state/`, so a re-run continues where it stopped and
appends to `data/interim/crawled_listings.csv`. A page that fails to download is retried next run.

## Scheduler

    python -m konu.scheduler --every 24 --limit 5000   # every 24 h, up to 5000 new pages per site per run
    python -m konu.scheduler --at 02:30 --limit 0      # daily at 02:30 local time, no page cap
    python -m konu.scheduler --once                    # one run, for cron or a systemd timer

- Each run resumes from the last, so a capped schedule gradually covers whole sites, then keeps picking up new listings.
- A lock file stops overlapping runs; a failed run is logged and the schedule carries on.
- Logs go to `logs/pipeline.log` (rotated). Stop with Ctrl+C or SIGTERM; it finishes cleanly.
- To run it unattended, use cron (`30 2 * * * cd /path/to/KONU && .venv/bin/python -m konu.scheduler --once --limit 5000`)
  or keep the long-running form under systemd/`nohup`/a container.

### How long a full crawl takes

At the default 1 s delay each site is limited to about 3,600 pages an hour, and sites run in parallel, so the
slowest site sets the pace. Approximate page counts: NoBroker 50k+ index pages plus every listing they link to,
MagicBricks about 29k, SquareYards about 28k resale pages plus about 7k projects, RealestateIndia about 20k, PropTiger about 13k.
Expect days for a first complete pass; that is what the scheduler is for. Lower `--delay` only if the sites tolerate it.

## Pipeline stages

1. **Crawl** (`konu/crawl.py`, `konu/sources/`): fetch new pages from the live sites into `data/interim/crawled_listings.csv`.
2. **Merge** (`konu/legacy.py`, `konu/pipeline.py`): align the archive and crawled rows to one schema (`konu/schema.py`) and drop rows that are identical in every column. URL is not a unique key, because one project page can list many units.
3. **Pincode enrichment** (`konu/pincode.py`): for rows with coordinates, a point-in-polygon test against the official India Post boundaries in `data/geo/` fills missing `Pincode` values (existing ones are kept) and adds `Possible_Pincodes`, the 3 nearest zones within 5 km, nearest first.
4. **Write** one CSV with the 42 columns listed in `konu/schema.py`.

## Layout

    konu/              pipeline package (schema, http, parsing, crawl, legacy, pincode, pipeline, scheduler)
    konu/sources/      one module per live site: urls() + parse()
    data/raw/          archived multi-site CSV (input)
    data/geo/          pincode boundary GeoJSON for Telangana and Andhra Pradesh (input)
    data/interim/      crawler output and per-site resume state
    logs/              scheduler log (git-ignored)
    tests/             offline unit tests: python -m unittest discover -s tests
    data/output/       the final single CSV
    tsrera/            separate tool for TS RERA project records (needs a human-typed captcha, see tsrera/README.md)

## Adding another website

Create `konu/sources/<site>.py` with `urls(fetcher, **opts)` (yield listing URLs) and
`parse(url, raw)` (return a dict using the columns in `konu/schema.py`, via `base_row`), then register
it in `konu/sources/__init__.py`.

## Data notes

- Pincode boundaries: [data.gov.in](https://www.data.gov.in/catalog/all-india-pincode-boundary-geo-json), via the [er-data-storage/postal-code-data](https://github.com/er-data-storage/postal-code-data) mirror.
- PropTiger rows are one per project: `Price_INR`/`Area_Sqft` are the minimum, `Price_Max_INR`/`Area_Max_Sqft` the maximum. Completed projects often show "Price on request" (empty price).
- Some archived columns are inconsistent as scraped (for example date-like text in `Transaction`, mixed `YearMonth` formats). They are preserved as is.
- MagicBricks rows are project-level; BHK and area are not published on those pages, so they are empty. `Total_Units`, `Rating`, `Review_Count` and `Posted_On` are filled where a site provides them.
- NoBroker and SquareYards listing pages can disappear once a property is sold; a failed download is retried on the next run.
