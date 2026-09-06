# KONU

Telangana real-estate data pipeline: property listings (nobroker.in / squareyards.com /
magicbricks.com) cleaned, imputed, and entity-matched against the TS RERA project
registry, producing a house-price-prediction-ready dataset and an Excel report.

## Layout

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

notebooks/                01 EDA · 02 merge · 03 modeling dataset · 04 in-depth EDA · 05 preprocessing
tsrera/                   TS RERA scraper (see tsrera/README.md)
data/raw/                 source datasets (gitignored)
data/processed/           pipeline outputs (gitignored)
data/reports/             Excel workbook (gitignored)
```

## Running

```bash
pip install -r requirements.txt
python3 -m konu.etl.run_etl        # -> data/processed/*.csv + data/reports/*.xlsx
jupyter notebook notebooks/        # exploratory analysis
```

Notebooks 03-05 cover the **sale-only** price-model path; the ETL produces the
**general** cleaned dataset across all deal types.

## Outputs

| File | What |
|---|---|
| `model_cleaned_listings.csv` | 90,039 rows, human-readable categories |
| `model_ready_listings.csv` | one-hot encoded, leakage-free feature matrix |
| `sale_listings.csv` / `rental_listings.csv` | split by deal type |
| `KONU_Real_Estate_Analysis.xlsx` | 12-sheet report incl. Methodology + Imputation_Summary |

## Key decisions

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
| locality mode | 54.5% | 98% |
| spatial KNN (lat/long) | 67.6% | — |
| society mode | 70.6% | 88% |
| **layered chain (shipped)** | **68.5%** | **99.8%** |

Result: 95.1% of rows carry a pincode. Roughly 1 in 3 imputed values is wrong, so
`Pincode_was_missing` and `Pincode_impute_source` travel with the data — use it as a coarse
geographic feature, not a verified address. The remaining 4.9% have no society, no
coordinates and no known locality, and are left null rather than guessed.

**RERA fields are never imputed.** `rera_promoter_name`, `rera_approved_date` and friends are
only populated where a listing actually matched a project. Filling them would fabricate a
government record; `has_rera_match` carries that signal instead.

**Leakage.** `Price_Cr` and `PricePerSqft` are deterministic functions of `Price_INR`; they
stay on the cleaned table for reference but are excluded from the feature matrix.

## Matching

No shared ID exists between listings and RERA. Listings are linked by fuzzy name match on
`Society` vs RERA project name, blocked on pincode where available (threshold 85), falling
back to a name-only match (threshold 90). Locality is deliberately not a blocking key —
listings use neighbourhood names ("Madhapur"), RERA uses formal village/mandal names. Match
rate is 16.4%; every row carries `match_score` and `match_method`.
