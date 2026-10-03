"""squareyards.com Hyderabad resale listings and new-project pages.

Resale discovery pages through the city listing index (25 listings per page); projects come from
the public project sitemaps filtered to /hyderabad-residential-property/.
"""
import re

from ..parsing import SQFT_PER, age_group, base_row, money, num, to_text
from .common import first, sitemap_locs

SOURCE = "squareyards.com"
BASE = "https://www.squareyards.com"
SALE_INDEX = BASE + "/sale/property-for-sale-in-hyderabad"
RENT_INDEX = BASE + "/rent/property-for-rent-in-hyderabad"
SITEMAP_INDEX = BASE + "/sitemap-index.xml"
LISTING_RE = re.compile(r'href="(https://www\.squareyards\.com/(?:resale|rent)-[^"#?]+/\d+)"')
MAX_PAGES = 5000  # safety stop; the real end is detected when a page yields no listings


def _extract(html):
    return list(dict.fromkeys(LISTING_RE.findall(html)))


def _listing_urls(fetcher, done, index_url):
    """Walk ?page=1..N of a city index until a page has no listings; finished pages are skipped on resume."""
    for page in range(1, MAX_PAGES + 1):
        page_url = f"{index_url}?page={page}"
        if page_url in done:
            continue
        links = _extract(fetcher.get(page_url) or "")
        if not links:
            return
        yield from links
        done.add(page_url)


def urls(fetcher, done=frozenset(), include_rent=False, **_):
    yield from _listing_urls(fetcher, done, SALE_INDEX)
    if include_rent:
        yield from _listing_urls(fetcher, done, RENT_INDEX)
    for sitemap in (u for u in sitemap_locs(fetcher, SITEMAP_INDEX) if re.search(r"sitemap-project\d+\.xml", u)):
        for url in sitemap_locs(fetcher, sitemap):
            if "/hyderabad-residential-property/" in url and url.endswith("/project"):
                yield url


def parse(url, raw):
    if url.endswith("/project"):
        return _parse_project(url, raw)
    return _parse_listing(url, raw)


def _lat_lon(raw):
    lat = first(r'"?lat(?:itude)?"?\s*[:=]\s*"?([\d.]+)', raw)
    lon = first(r'"?lon(?:g|gitude)?"?\s*[:=]\s*"?([\d.]+)', raw)
    return lat, lon


def _parse_listing(url, raw):
    t = to_text(raw)
    slug = url.split("/")[-2]
    kind = "Rent" if slug.startswith("rent-") else "Sale"
    price = money(first(r"Listing ID: #\d+\s*₹\s*([\d.,]+\s*(?:Cr|Crores?|L|Lacs?|K)?)", t))
    area_m = re.search(r"Area\s+(?:(?:Carpet|Built-up|Super Built-up|Plot) Area\s+)?([\d,.]+)\s*(Sq\.?\s?Ft|Sq\.?\s?Yd|Sq\.?\s?Yards?|Sq\.?\s?M)", t, re.I)
    area = None
    if area_m:
        unit = area_m.group(2).lower()
        area = num(area_m.group(1)) * (SQFT_PER["sq.yards"] if "y" in unit else SQFT_PER["sq.meter"] if unit.endswith("m") else 1)
    if not (price or area):
        return None
    info = t[t.find("Property Information"):]
    locality, _, project = first(r"Locality\s+(.+?)\s+Price", info).partition(" Project ")
    city = first(r"City\s+(\w+(?: \w+)?)\s+Micro market", info) or "Hyderabad"
    slug_place = first(r"-in-(.+)$", slug)
    society = project or ("" if re.sub(r"[^a-z]", "", locality.lower()) == re.sub(r"[^a-z]", "", slug_place)
                          else slug_place.replace("-", " ").title())
    age = first(r"Age of (?:Property|Building)\s+(.+?)\s+(?:Facing|Floor|Ownership|View)", t)
    lat, lon = _lat_lon(raw)
    bhk = first(r"^(?:resale|rent)-([\d-]+)-bhk", slug).replace("-", ".")
    return base_row(url, SOURCE, price, area, dict(
        BHK=bhk or first(r"(\d+)\s*Bedrooms?", t), Bathrooms=num(first(r"Number of Bathroom\s+(\d+)", t)) or "",
        Floor_Number=first(r"Floor Number\s+(\w+)", t), Total_Floors=first(r"Total Floors?\s+(\d+)", t),
        Property_Age_Years=num(age) if age else "", Age_Group=age_group(num(age)) if age else "",
        Locality=locality, Society=society, Facing=first(r"Facing\s+([A-Za-z -]+?)\s+(?:View|Power|Flooring)", t),
        Furnishing=first(r"Furnishing\s+([A-Za-z -]+?)\s+(?:Facing|Floor|View|Power)", t),
        Construction_Status=first(r"Possession Status\s+(.+?)\s+(?:View Number|Request)", t),
        Transaction="Resale" if kind == "Sale" else "Rent", Listing_Type=kind,
        Property_Type=first(r"sq-(?:ft|yd)-(.+?)-in-", slug).replace("-", " ").title(),
        Latitude=lat, Longitude=lon, Full_Address=", ".join(x for x in (society, locality, city, "India") if x),
    ))


def _parse_project(url, raw):
    t = to_text(raw)
    name = url.split("/")[-3].replace("-", " ").title()
    units = re.findall(r"(\d(?:\.\d)?)\s*BHK\s+\w+\s+([\d,]+)\s*Sq\.?\s?Ft\.?\s+(Price on Request|₹\s*[\d.,]+\s*(?:Cr|L|Lac|K)?)", t, re.I)
    if not units:
        return None
    prices = [money(p) for _, _, p in units if p.startswith("₹")]
    areas = [num(a) for _, a, _ in units]
    lat, lon = _lat_lon(raw)
    locality = first(r"compared with (.+?)\.", t)
    avg = first(r"avg\. price is ₹\s*([\d.,]+\s*k?)", t, flags=re.I)
    avg_val = (num(avg) or 0) * (1000 if avg.lower().endswith("k") else 1)
    return base_row(url, SOURCE, min(prices) if prices else None, min(areas), dict(
        BHK="/".join(dict.fromkeys(b for b, _, _ in units)), Society=name, Locality=locality,
        Transaction="New Property", Listing_Type="Sale", Property_Type="Project",
        Price_Max_INR=round(max(prices)) if prices else "", Area_Max_Sqft=max(areas),
        PricePerSqft=avg_val or "", Latitude=lat, Longitude=lon,
        Full_Address=", ".join(x for x in (name, locality, "Hyderabad", "India") if x),
    ))
