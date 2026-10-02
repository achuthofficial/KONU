#!/usr/bin/env python3
"""Crawl Hyderabad property listings from RealestateIndia and PropTiger.

Writes a separate CSV (default: crawled_listings.csv) using the same column
names as `All_Merged_Updated(in).csv`, plus a few extra columns. Nothing in the
existing CSV is modified.

Discovery uses each site's public sitemap. robots.txt is checked before every
fetch, requests are rate-limited, and progress is checkpointed so a run can be
stopped and resumed.

    python crawler/crawl.py --sources realestateindia,proptiger --limit 200
    python crawler/crawl.py --sources realestateindia --include-rent --limit 0   # 0 = no limit
"""
import argparse
import csv
import gzip
import html
import json
import os
import re
import sys
import time
import urllib.robotparser
from datetime import date

import requests

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"

COLUMNS = [
    "URL", "YearMonth", "Year", "Month", "Price_INR", "Price_Cr", "PricePerSqft", "BHK", "Area_Sqft",
    "Bathrooms", "Balconies", "Car_Parking", "Floor_Number", "Total_Floors", "Property_Age_Years",
    "Age_Group", "Locality", "Pincode", "Society", "Furnishing", "Facing", "Ownership", "Overlooking",
    "Transaction", "Construction_Status", "Latitude", "Longitude", "Full_Address",
    # extras not in the original CSV
    "Source", "Listing_Type", "Property_Type", "Price_Max_INR", "Area_Max_Sqft", "Builder", "RERA_ID",
]

SQFT_PER = {"sq.ft.": 1, "sq.ft": 1, "sq. yards": 9, "sq.yards": 9, "sq. meter": 10.7639, "sq.meter": 10.7639,
            "acre": 43560, "cent": 435.6, "guntha": 1089, "ares": 1076.39, "hectares": 107639}


# ----------------------------------------------------------------------------- helpers
def to_text(raw):
    h = html.unescape(raw)
    t = re.sub(r"<script.*?</script>|<style.*?</style>|<[^>]+>", " ", h, flags=re.S)
    return re.sub(r"\s+", " ", t)


def money(s):
    """'1.5 Cr' / '68 Lac' / '2.00 L' / '₹ 5,000' -> rupees (float) or None."""
    if not s:
        return None
    m = re.search(r"([\d,]+(?:\.\d+)?)\s*(Cr|Crore|Lac|Lakh|L|K)?\b", s.replace("₹", " "), re.I)
    if not m:
        return None
    v = float(m.group(1).replace(",", ""))
    unit = (m.group(2) or "").lower()
    mult = {"cr": 1e7, "crore": 1e7, "lac": 1e5, "lakh": 1e5, "l": 1e5, "k": 1e3}.get(unit, 1)
    return v * mult


def num(s):
    m = re.search(r"[\d,]+(?:\.\d+)?", s or "")
    return float(m.group(0).replace(",", "")) if m else None


def age_group(y):
    if y is None:
        return ""
    return "New" if y <= 1 else "1-5 Years" if y <= 5 else "6-10 Years" if y <= 10 else "10+ Years"


def base_row(url, source, price, area, extra=None):
    today = date.today()
    r = {c: "" for c in COLUMNS}
    r.update(URL=url, Source=source, Year=today.year, Month=today.month, YearMonth=today.strftime("%Y-%m"))
    if price:
        r["Price_INR"] = round(price)
        r["Price_Cr"] = round(price / 1e7, 4)
    if area:
        r["Area_Sqft"] = round(area, 2)
        if price:
            r["PricePerSqft"] = round(price / area, 2)
    r.update(extra or {})
    return r


# ----------------------------------------------------------------------------- RealestateIndia
REI_KEYS = ["Listing Type", "Building Type", "Property Type", "City", "Locality", "Price", "Number of Rooms",
            "Balcony", "Number of Bathroom", "Built Up Area", "Carpet Area", "Super Area", "Plot/Land Area", "Plot Area", "Ownership",
            "Sale Type", "Age of Property", "Project & Society", "Floor Number", "Total Floor Count",
            "Power Back-up", "Booking Amount", "Maintenance Charge", "Furnishing", "Facing", "Status",
            "Amenities", "Location & Connectivity"]


def parse_rei(url, raw):
    t = to_text(raw)
    i = t.find("Property Information")
    if i < 0:
        return None
    seg = t[i:]
    pos = sorted((m.start(), k, m.end()) for k in REI_KEYS for m in [re.search(r"(?<![A-Za-z])" + re.escape(k) + r"(?![A-Za-z])", seg)] if m)
    kv = {}
    for n, (s, k, e) in enumerate(pos):
        kv[k] = seg[e: pos[n + 1][0] if n + 1 < len(pos) else len(seg)].strip()
    if kv.get("Listing Type", "").split(" ")[0] not in ("Sale", "Rent", "Lease"):
        return None
    price = money(kv.get("Price"))
    area_txt = kv.get("Built Up Area") or kv.get("Super Area") or kv.get("Carpet Area") or kv.get("Plot/Land Area") or kv.get("Plot Area") or ""
    area, unit = num(area_txt), (re.search(r"[\d.,]+\s*(Sq\.?\s?(?:ft|Yards|Meter)\.?|Acre|Cent|Guntha|Ares|Hectares)", area_txt, re.I) or [None, "Sq.ft."])[1]
    unit = re.sub(r"\s+", " ", unit.lower()).replace("sq. ft", "sq.ft")
    area = area * SQFT_PER.get(unit, 1) if area else None
    name = re.search(r'"name":\s*"([^"]*)"', raw)
    bhk = re.search(r"(\d(?:\.\d)?)\s*BHK", (name.group(1) if name else "") + " " + url.replace("-", " "), re.I) or re.search(r"(\d(?:\.\d)?)\s*bkh", url, re.I)
    ll = re.search(r'"latitude":\s*"?([\d.]+)"?,\s*"longitude":\s*"?([\d.]+)', raw)
    age = kv.get("Age of Property", "")
    age_y = 0.0 if "new" in age.lower() else num(age)
    sale_type = kv.get("Sale Type", "")
    loc = kv.get("Locality", "")
    society = kv.get("Project & Society", "")
    row = base_row(url, "realestateindia.com", price, area, dict(
        BHK=bhk.group(1) if bhk else "", Bathrooms=num(kv.get("Number of Bathroom")) or "",
        Balconies=num(kv.get("Balcony")) or "", Floor_Number=kv.get("Floor Number", ""),
        Total_Floors=num(kv.get("Total Floor Count")) or "", Property_Age_Years=age_y if age_y is not None else "",
        Age_Group=age_group(age_y), Locality=loc, Society=society, Furnishing=kv.get("Furnishing", ""),
        Facing=kv.get("Facing", ""), Ownership=kv.get("Ownership", ""), Transaction=sale_type or kv["Listing Type"],
        Construction_Status=kv.get("Status", ""), Latitude=ll.group(1) if ll else "", Longitude=ll.group(2) if ll else "",
        Full_Address=", ".join(x for x in (society, loc, "Hyderabad", "India") if x),
        Listing_Type=kv["Listing Type"].split(" ")[0], Property_Type=kv.get("Property Type", ""),
    ))
    return row if (price or area) else None


def rei_urls(include_rent, session, log):
    idx = fetch(session, "https://www.realestateindia.com/sitemap_index.xml", log)
    kinds = ("property-detail-buy",) + (("property-detail-rent",) if include_rent else ())
    for sm in re.findall(r"<loc>([^<]+)</loc>", idx or ""):
        if any(k in sm for k in kinds):
            body = fetch(session, sm, log)
            for u in re.findall(r"<loc>([^<]+)</loc>", body or ""):
                if "-hyderabad-" in u or u.endswith("-hyderabad.htm") or "hyderabad" in u.split("/")[-1]:
                    if re.search(r"flat|apartment|villa|house|floor|penthouse|studio|plot|land", u):
                        if not re.search(r"agricultur|farm|commercial|office|shop|warehouse|godown", u):
                            yield u


# ----------------------------------------------------------------------------- PropTiger
def parse_pt(url, raw):
    ld = None
    for blk in re.findall(r"ld\+json[^>]*>(.*?)</script>", raw, re.S):
        try:
            d = json.loads(blk)
        except ValueError:
            continue
        if isinstance(d, dict) and d.get("@type") in ("ApartmentComplex", "Residence", "Apartment"):
            ld = d
            break
    if not ld:
        return None
    t = to_text(raw)
    k = t.find("(show on map)")
    head = t[k : k + 900] if k >= 0 else t
    pre = t[max(0, k - 200) : k] if k >= 0 else ""
    pr = re.search(r"₹\s*([\d.,]+\s*(?:Cr|L|Lac))\s*(?:-\s*₹\s*([\d.,]+\s*(?:Cr|L|Lac)))?", head)
    cfg = re.search(r"Configuration\s+([\d.,\s/]+(?:BHK|RK)?[^A-Za-z]*(?:BHK|RK)?)", head)
    ar = re.search(r"sq ft\s+([\d,]+)\s*(?:-\s*([\d,]+))?\s*sq ft", head)
    avg = re.search(r"Avg\. Price\s*₹\s*([\d,]+)", head)
    poss = re.search(r"Possession\s*:?\s*([A-Za-z]{3}'\d{2})", t)
    status = re.search(r"Possession Status\s+([A-Za-z ]+?)\s+(?:Avg|Price)", head)
    rera = re.search(r"RERA ID\s+([A-Z0-9/\-]+)", t)
    builder = re.search(r"\bby\s+(.+?)\s+" + re.escape(ld["address"]["addressLocality"].split(",")[0]) + r",", pre)
    geo = ld.get("geo", {})
    loc = ld.get("address", {}).get("addressLocality", "").replace(", Hyderabad", "")
    pmin = money(pr.group(1)) if pr else None
    pmax = money(pr.group(2)) if pr and pr.group(2) else None
    amin = num(ar.group(1)) if ar else None
    amax = num(ar.group(2)) if ar and ar.group(2) else None
    bhks = re.findall(r"\d(?:\.\d)?", cfg.group(1)) if cfg else []
    row = base_row(url, "proptiger.com", pmin, amin, dict(
        BHK="/".join(bhks), Locality=loc, Society=ld.get("name", ""), Transaction="New Property",
        Construction_Status=(status.group(1).strip() if status else "") or (poss.group(1) if poss else ""),
        Latitude=geo.get("latitude", ""), Longitude=geo.get("longitude", ""),
        Full_Address=", ".join(x for x in (ld.get("name"), loc, "Hyderabad", "India") if x),
        Listing_Type="Sale", Property_Type=ld.get("@type", ""), Price_Max_INR=round(pmax) if pmax else "",
        Area_Max_Sqft=amax or "", Builder=builder.group(1) if builder else "", RERA_ID=rera.group(1) if rera else "",
    ))
    if avg:
        row["PricePerSqft"] = float(avg.group(1).replace(",", ""))
    return row if (pmin or amin) else None


def pt_urls(session, log):
    idx = fetch(session, "https://www.proptiger.com/secure-sitemap-index.xml", log)
    for sm in re.findall(r"<loc>([^<]+)</loc>", idx or ""):
        if re.search(r"secure-sitemap-project(-\d+)?\.xml", sm):
            body = fetch(session, sm, log, binary_gz=sm.endswith(".gz"))
            for u in re.findall(r"<loc>([^<]+)</loc>", body or ""):
                if "/hyderabad/" in u:
                    yield u


# ----------------------------------------------------------------------------- fetching
class Polite:
    def __init__(self, delay):
        self.delay, self.last, self.robots = delay, 0.0, {}

    def allowed(self, url):
        host = re.match(r"https?://[^/]+", url).group(0)
        if host not in self.robots:
            rp = urllib.robotparser.RobotFileParser()
            try:
                txt = requests.get(host + "/robots.txt", headers={"User-Agent": UA}, timeout=20).text
                rp.parse(txt.splitlines())
            except requests.RequestException:
                rp.parse([])
            self.robots[host] = rp
        return self.robots[host].can_fetch(UA, url)

    def wait(self):
        d = self.last + self.delay - time.time()
        if d > 0:
            time.sleep(d)
        self.last = time.time()


POLITE = None


def fetch(session, url, log, binary_gz=False, tries=3):
    if not POLITE.allowed(url):
        log(f"robots.txt disallows {url}")
        return None
    for n in range(tries):
        POLITE.wait()
        try:
            r = session.get(url, timeout=40)
        except requests.RequestException as e:
            log(f"{url}: {e}")
            time.sleep(2 ** n)
            continue
        if r.status_code == 200:
            if binary_gz or url.endswith(".gz"):
                try:
                    return gzip.decompress(r.content).decode("utf-8", "ignore")
                except OSError:
                    return r.text
            return r.text
        if r.status_code in (403, 429, 503):
            log(f"{url}: HTTP {r.status_code}, backing off")
            time.sleep(10 * (n + 1))
            continue
        log(f"{url}: HTTP {r.status_code}")
        return None
    return None


# ----------------------------------------------------------------------------- main
def main():
    global POLITE
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", default="realestateindia,proptiger")
    ap.add_argument("--limit", type=int, default=100, help="max detail pages per source this run (0 = unlimited)")
    ap.add_argument("--delay", type=float, default=1.0, help="seconds between requests")
    ap.add_argument("--include-rent", action="store_true", help="RealestateIndia: also crawl rent listings")
    ap.add_argument("--out", default="crawled_listings.csv")
    ap.add_argument("--state", default="crawler/.state.json", help="checkpoint of URLs already fetched")
    a = ap.parse_args()
    POLITE = Polite(a.delay)
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "en-IN,en;q=0.9"})
    log = lambda m: print(m, file=sys.stderr, flush=True)

    done = set(json.load(open(a.state))) if os.path.exists(a.state) else set()
    new_file = not os.path.exists(a.out)
    os.makedirs(os.path.dirname(a.state) or ".", exist_ok=True)
    out = open(a.out, "a", newline="", encoding="utf-8")
    w = csv.DictWriter(out, fieldnames=COLUMNS)
    if new_file:
        w.writeheader()

    sources = {
        "realestateindia": (lambda: rei_urls(a.include_rent, s, log), parse_rei),
        "proptiger": (lambda: pt_urls(s, log), parse_pt),
    }
    for name in a.sources.split(","):
        urls, parser = sources[name.strip()]
        ok = skipped = failed = 0
        for u in urls():
            if u in done:
                continue
            if a.limit and ok + failed >= a.limit:
                break
            raw = fetch(s, u, log)
            done.add(u)
            row = parser(u, raw) if raw else None
            if row:
                w.writerow(row)
                ok += 1
            else:
                failed += 1
            if (ok + failed) % 25 == 0:
                out.flush()
                json.dump(sorted(done), open(a.state, "w"))
                log(f"[{name}] parsed={ok} failed={failed}")
        out.flush()
        json.dump(sorted(done), open(a.state, "w"))
        log(f"[{name}] finished: parsed={ok} failed/skipped={failed}")
    out.close()


if __name__ == "__main__":
    main()
