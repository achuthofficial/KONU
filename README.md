# KONU

Telangana / Hyderabad real-estate data, in two parts:

1. **Data collection pipeline** (`konu.pipeline`, `konu.scheduler`): crawls listing sites on a schedule, merges them with the
   archived dataset, fills pincodes, and writes one CSV.
2. **Analysis ETL and notebooks** (`konu.etl`, `konu.matching`, `notebooks/`): cleans and imputes the listings, matches them to
   the TS RERA registry, and prepares a price-model dataset.

## Part 1: Data collection pipeline

One command collects property listings from several websites, merges them with the
archived dataset, fills in missing pincodes from coordinates, and writes
**everything to a single CSV**:

    data/output/properties_all_sources.csv

### Sources

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

### Setup

    python3 -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt

### Run once

    python -m konu.pipeline                  # crawl 100 new pages per site, merge, enrich -> final CSV
    python -m konu.pipeline --limit 0        # crawl everything (see "How long a full crawl takes")
    python -m konu.pipeline --skip-crawl     # rebuild the final CSV from existing data (about 15 s)

Options: `--sources nobroker,magicbricks,...`, `--limit N`, `--delay SECONDS`, `--include-rent`.
Sites are crawled in parallel (one thread and rate limiter per site). Crawling is resumable:
visited pages are tracked per site in `data/interim/state/`, so a re-run continues where it stopped and
appends to `data/interim/crawled_listings.csv`. A page that fails to download is retried next run.

### Scheduler

    python -m konu.scheduler --every 24 --limit 5000   # every 24 h, up to 5000 new pages per site per run
    python -m konu.scheduler --at 02:30 --limit 0      # daily at 02:30 local time, no page cap
    python -m konu.scheduler --once                    # one run, for cron or a systemd timer

- Each run resumes from the last, so a capped schedule gradually covers whole sites, then keeps picking up new listings.
- A lock file stops overlapping runs; a failed run is logged and the schedule carries on.
- Logs go to `logs/pipeline.log` (rotated). Stop with Ctrl+C or SIGTERM; it finishes cleanly.
- To run it unattended, use cron (`30 2 * * * cd /path/to/KONU && .venv/bin/python -m konu.scheduler --once --limit 5000`)
  or keep the long-running form under systemd/`nohup`/a container.

#### How long a full crawl takes

At the default 1 s delay each site is limited to about 3,600 pages an hour, and sites run in parallel, so the
slowest site sets the pace. Approximate page counts: NoBroker 50k+ index pages plus every listing they link to,
MagicBricks about 29k, SquareYards about 28k resale pages plus about 7k projects, RealestateIndia about 20k, PropTiger about 13k.
Expect days for a first complete pass; that is what the scheduler is for. Lower `--delay` only if the sites tolerate it.

### Pipeline stages

1. **Crawl** (`konu/crawl.py`, `konu/sources/`): fetch new pages from the live sites into `data/interim/crawled_listings.csv`.
2. **Merge** (`konu/legacy.py`, `konu/pipeline.py`): align the archive and crawled rows to one schema (`konu/schema.py`) and drop rows that are identical in every column. URL is not a unique key, because one project page can list many units.
3. **Pincode enrichment** (`konu/pincode.py`): for rows with coordinates, a point-in-polygon test against the official India Post boundaries in `data/reference/` fills missing `Pincode` values (existing ones are kept) and adds `Possible_Pincodes`, the 3 nearest zones within 5 km, nearest first.
4. **Write** one CSV with the 42 columns listed in `konu/schema.py`.

### Layout

    konu/              pipeline package (schema, http, parsing, crawl, legacy, pincode, pipeline, scheduler)
    konu/sources/      one module per live site: urls() + parse()
    data/raw/          archived multi-site CSV legacy_listings.csv (input; other files here are git-ignored)
    data/reference/          pincode boundary GeoJSON for Telangana and Andhra Pradesh (input)
    data/interim/      crawler output and per-site resume state
    logs/              scheduler log (git-ignored)
    tests/             offline unit tests: python -m unittest discover -s tests
    data/output/       the final single CSV
    tsrera/            separate tool for TS RERA project records (needs a human-typed captcha, see tsrera/README.md)

### Adding another website

Create `konu/sources/<site>.py` with `urls(fetcher, **opts)` (yield listing URLs) and
`parse(url, raw)` (return a dict using the columns in `konu/schema.py`, via `base_row`), then register
it in `konu/sources/__init__.py`.

### Data notes

- Pincode boundaries: [data.gov.in](https://www.data.gov.in/catalog/all-india-pincode-boundary-geo-json), via the [er-data-storage/postal-code-data](https://github.com/er-data-storage/postal-code-data) mirror.
- PropTiger rows are one per project: `Price_INR`/`Area_Sqft` are the minimum, `Price_Max_INR`/`Area_Max_Sqft` the maximum. Completed projects often show "Price on request" (empty price).
- Some archived columns are inconsistent as scraped (for example date-like text in `Transaction`, mixed `YearMonth` formats). They are preserved as is.
- MagicBricks rows are project-level; BHK and area are not published on those pages, so they are empty. `Total_Units`, `Rating`, `Review_Count` and `Posted_On` are filled where a site provides them.
- NoBroker and SquareYards listing pages can disappear once a property is sold; a failed download is retried on the next run.

## Part 2: Analysis ETL and notebooks

Telangana real-estate data pipeline: property listings (nobroker.in / squareyards.com /
magicbricks.com) cleaned, imputed, and entity-matched against the TS RERA project
registry, producing a house-price-prediction-ready dataset and an Excel report.

### Layout

```
konu/                     analysis package
├── paths.py              canonical data paths
├── etl/
│   ├── extract.py        load raw CSVs with correct dtypes
│   ├── clean.py          category normalization, deal-type parsing, winsorizing
│   ├── impute.py         per-column imputation + _was_missing flags
│   ├── transform.py      merge, clean, impute, engineer; enforces the loss budget
│   ├── report.py         summary tables for the workbook
│   ├── load.py           CSV + formatted Excel output
│   └── run_etl.py        entrypoint
└── matching/
    └── entity_match.py   fuzzy listing <-> RERA project resolution

notebooks/                01 EDA · 02 merge · 03 modeling dataset · 04 in-depth EDA · 05 preprocessing · 06 pincode matching
tsrera/                   TS RERA scraper (see tsrera/README.md)
data/raw/                 source datasets (gitignored)
data/processed/           pipeline outputs (gitignored)
data/reports/             Excel workbook (gitignored)
data/reference/           pincode boundary GeoJSON, tracked (see its README for provenance)
```

### Running

```bash
pip install -r requirements.txt
python3 -m konu.etl.run_etl        # -> data/processed/*.csv + data/reports/*.xlsx
# the ETL reads data/raw/All_Merged_Updated.csv, or data/raw/legacy_listings.csv if that file is absent
jupyter notebook notebooks/        # exploratory analysis
```

Notebooks 03-05 cover the **sale-only** price-model path; the ETL produces the
**general** cleaned dataset across all deal types.

### Outputs

| File | What |
|---|---|
| `model_cleaned_listings.csv` | 90,039 rows, human-readable categories |
| `model_ready_listings.csv` | one-hot encoded, leakage-free feature matrix |
| `sale_listings.csv` / `rental_listings.csv` | split by deal type |
| `KONU_Real_Estate_Analysis.xlsx` | 12-sheet report incl. Methodology + Imputation_Summary |

### Key decisions

**Data-loss budget.** Row loss vs the raw file is held under **5%** (currently 3.83%);
`transform.run()` raises if a change pushes it over. The only row-drop is a missing or
non-positive price/area. Everything else is impute, cap, or flag.

**Winsorizing is per deal type.** Sale prices, monthly rents and lease deposits share one
`Price_INR` column three orders of magnitude apart. A global 1st-percentile floor lands at
~₹27,000 — above the median monthly rent — and would inflate ~46% of rent rows up to it.

**Imputation is chosen per column, and flagged.** Fields that scale with unit size
(bathrooms, balconies, floors) get median-within-BHK, not a flat fill. Commodity prices get
median-within-month. `PricePerSqft` is recomputed, not imputed. Every imputed column ships a
`<column>_was_missing` flag.

**Pincode is imputed but not trustworthy as an address.** Only 26.8% of rows carried one.
Candidates were measured against held-out observed pincodes:

| method | accuracy | coverage |
|---|---|---|
| pincode boundary polygons | 41.4% | 93% |
| locality mode | 54.5% | 98% |
| spatial KNN (lat/long) | 67.6% | — |
| society mode | 70.6% | 88% |
| **layered chain (shipped)** | **68.5%** | **99.8%** |

Result: 95.1% of rows carry a pincode. Roughly 1 in 3 imputed values is wrong, so
`Pincode_was_missing` and `Pincode_impute_source` travel with the data — use it as a coarse
geographic feature, not a verified address. The remaining 4.9% have no society, no
coordinates and no known locality, and are left null rather than guessed.

**Why the boundary polygons don't fill pincode.** Point-in-polygon against official India
Post boundaries (`data/reference/*.geojson`) is the methodologically right approach and would
normally beat every statistical method — but it scores worst here, because the *coordinates*
can't support it. 84,393 rows carry only 8,353 distinct coordinates (9.9%); one point repeats
6,472 times. Where five or more pincode-bearing rows share a coordinate, 54% disagree on the
pincode, with up to 70 distinct pincodes at a single point. The coordinates are locality
centroids, not property locations, so a containment test returns one pincode for an area that
genuinely spans many. Appending polygons to the chain left accuracy unchanged (68.3%); putting
them ahead of the KNN made it worse (66.7%).

**What the polygons do give us**, since districts are far coarser than pincodes and survive
centroid-level coordinates:

| column | what | quality |
|---|---|---|
| `district_from_geo` | district containing the coordinate | 88.2% coverage, 80.1% agreement with RERA's district |
| `Possible_Pincodes` | 3 nearest pincode zones, nearest first | true pincode is among them 62% of the time |
| `pincode_matches_polygon` | does the imputed pincode agree with the containing polygon | independent confidence flag |

**RERA fields are never imputed.** `rera_promoter_name`, `rera_approved_date` and friends are
only populated where a listing actually matched a project. Filling them would fabricate a
government record; `has_rera_match` carries that signal instead.

**Leakage.** `Price_Cr` and `PricePerSqft` are deterministic functions of `Price_INR`; they
stay on the cleaned table for reference but are excluded from the feature matrix.

### Matching

No shared ID exists between listings and RERA. Listings are linked by fuzzy name match on
`Society` vs RERA project name, blocked on pincode where available (threshold 85), falling
back to a name-only match (threshold 90). Locality is deliberately not a blocking key —
listings use neighbourhood names ("Madhapur"), RERA uses formal village/mandal names. Match
rate is 16.4%; every row carries `match_score` and `match_method`.
