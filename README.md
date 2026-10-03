# KONU: Hyderabad property data pipeline

One command collects property listings from several websites, merges them with the
archived dataset, fills in missing pincodes from coordinates, and writes
**everything to a single CSV**:

    data/output/properties_all_sources.csv

## Sources

| Site | How it gets in |
|---|---|
| nobroker.in, magicbricks.com, squareyards.com, 99acres.com | archived dataset `data/raw/legacy_listings.csv` |
| realestateindia.com, proptiger.com | live crawl (public sitemaps, honours `robots.txt`) |

Archived rows with no URL (about 17k) cannot be traced to a site; they are kept and
labelled `Source = unknown (no URL)`. Filter on the `Source` column to pick any subset of sites.

## Setup

    python3 -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt

## Run

    # Crawl 100 new pages per live site, merge, enrich -> final CSV
    python -m konu.pipeline

    # Crawl everything (about 33k pages, many hours at the default 1 s delay)
    python -m konu.pipeline --limit 0

    # Rebuild the final CSV from existing data without touching the network (about 10 s)
    python -m konu.pipeline --skip-crawl

Options: `--sources realestateindia,proptiger`, `--limit N`, `--delay SECONDS`, `--include-rent`.
Crawling is resumable: visited URLs are tracked in `data/interim/.crawl_state.json`, so re-running
continues where it stopped and appends to `data/interim/crawled_listings.csv`.

## Pipeline stages

1. **Crawl** (`konu/crawl.py`, `konu/sources/`): fetch new listing pages from the live sites into `data/interim/crawled_listings.csv`.
2. **Merge** (`konu/legacy.py`, `konu/pipeline.py`): align the archive and crawled rows to one schema (`konu/schema.py`) and drop rows that are identical in every column. URL is not a unique key, because one project page can list many units.
3. **Pincode enrichment** (`konu/pincode.py`): for rows with coordinates, a point-in-polygon test against the official India Post boundaries in `data/geo/` fills missing `Pincode` values (existing ones are kept) and adds `Possible_Pincodes`, the 3 nearest zones within 5 km, nearest first.
4. **Write** one CSV with the 38 columns listed in `konu/schema.py`.

## Layout

    konu/              pipeline package (schema, http, parsing, crawl, legacy, pincode, pipeline)
    konu/sources/      one module per live site: urls() + parse()
    data/raw/          archived multi-site CSV (input)
    data/geo/          pincode boundary GeoJSON for Telangana and Andhra Pradesh (input)
    data/interim/      crawler output and checkpoint
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
- 99acres, Housing.com and Makaan are not crawled live (bot protection).
