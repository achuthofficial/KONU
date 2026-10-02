# Hyderabad listings crawler

Collects listings from **realestateindia.com** (resale/new flats, houses, villas, plots) and
**proptiger.com** (new-project pages) into a separate file, `crawled_listings.csv`, using the
same column names as `All_Merged_Updated(in).csv` plus: `Source`, `Listing_Type`, `Property_Type`,
`Price_Max_INR`, `Area_Max_Sqft`, `Builder`, `RERA_ID`. The existing CSV is never modified.

    pip install requests
    python crawler/crawl.py --sources realestateindia,proptiger --limit 200   # --limit 0 = everything
    python crawler/crawl.py --sources realestateindia --include-rent

- URLs come from each site's public sitemap (about 20k Hyderabad pages on RealestateIndia, about 13k on PropTiger).
- `robots.txt` is checked before every request, with a default 1 s delay (`--delay`).
- Progress is checkpointed in `crawler/.state.json`; re-running skips pages already fetched and appends to the CSV.
- PropTiger rows are one per project: `Price_INR`/`Area_Sqft` are the minimum and `Price_Max_INR`/`Area_Max_Sqft` the maximum. Completed projects often show "Price on request" (empty price).
- Not covered: 99acres, Housing.com and Makaan (bot protection), NoBroker/MagicBricks/SquareYards (already in the main CSV).
