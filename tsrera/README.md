# TS RERA extractor

Pulls project records from the public search at
`https://rerait.telangana.gov.in/SearchList/Search` — every district, every
result, every inner detail (General Info, Project Info, Land, Building,
Development Work, Professionals, Bank accounts, Uploaded documents).

## How it works

The site splits neatly into a metered part and a free part, and this tool
exploits that split:

| Phase | Endpoint | Captcha? | What you get |
|-------|----------|----------|--------------|
| **harvest** | `POST /SearchList/Search` | **yes**, per listing page (10 rows/page) | summary row + an encrypted per-project detail token |
| **enrich** | `GET /PrintPreview/PrintPreview?q=<token>` | **no** | the full detail page for each project |

So captchas are spent *only* to page through listings and collect tokens.
Once harvested, all the deep detail is fetched with no captcha at all.

The captcha is solved by a **human in the loop** — the tool saves the image
and asks you to type it. It does not attempt to defeat the captcha with OCR or a
solving service; that control is what keeps automated load off a government
server, and it's left in place on purpose.

TLS: the server omits the emSign intermediate cert, so `certs/bundle.pem`
(certifi + that intermediate) is used. Verification stays **on** — no `verify=False`.

## Usage

```bash
pip install requests beautifulsoup4 certifi

# 1. Harvest listings (this is where you type captchas)
python3 tsrera/run.py harvest --districts 25        # Hyderabad only
python3 tsrera/run.py harvest --districts 25,1,9     # a few
python3 tsrera/run.py harvest --districts all        # every district

# 2. Enrich — captcha-free, unattended, resumable
python3 tsrera/run.py enrich

# 3. Flatten to CSV
python3 tsrera/run.py export
```

Everything is **resumable**: rerun any phase and it skips what's already in
`data/rows.jsonl` / `data/details.jsonl` (tracked in `data/progress.json`).
Kill it anytime and continue later.

## Captcha cost

Listings are 10 rows/page and each page submit may require a captcha. The
harvester tries to advance the pager *without* one first and only prompts when
the server actually demands it — so the real cost depends on whether the site
re-checks the captcha while paging (the tool discovers this on its first run).
Worst case it is one captcha per listing page:

- Hyderabad alone: 578 records → 58 pages.
- Statewide is far larger.

If that hand-typing cost is impractical for a full dump, RERA data is a
statutory public disclosure — an RTI / written data request to TS RERA is the
clean route to the whole dataset in bulk. This scraper is then best used for
targeted district or project lookups.

## Files

- `client.py` — HTTP client: search, pager, captcha-free detail fetch, listing parser.
- `detail_parser.py` — turns a PrintPreview page into `{sections, tables, raw_labels}`.
- `run.py` — `harvest` / `enrich` / `export` orchestrator, resumable.
- `certs/bundle.pem` — CA bundle incl. the missing emSign intermediate.
- `data/` — output (git-ignored): `rows.jsonl`, `details.jsonl`, `projects.csv`.
