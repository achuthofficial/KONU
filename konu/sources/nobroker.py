"""nobroker.in owner listings (flats, houses, villas, plots) for Hyderabad.

Discovery: the sitemap index lists Hyderabad index pages (per locality / BHK / building). Each
index page links to its property detail pages, which carry the full field set.
"""
import re

from ..parsing import SQFT_PER, age_group, base_row, money, num, to_text
from .common import crawl_listing_pages, first, sitemap_locs

SOURCE = "nobroker.in"
SITEMAP_INDEX = "https://www.nobroker.in/sitemap/sitemap_index.xml"
BASE = "https://www.nobroker.in"
DETAIL_RE = re.compile(r'href="(/property/(?:buy|rent)/[^"#?]+/detail)')

# Broad locality pages first, then the (much larger) per-building pages.
SALE_SITEMAPS = [r"sale_hyderabad_properties", r"sale_hyderabad_locality_", r"plot_hyderabad_locality_misc",
                 r"new-flats-for-sale-hyderabad", r"sale_hyderabad_nb_building_new"]
RENT_SITEMAPS = [r"rent_hyderabad_properties", r"rent_hyderabad_locality_", r"rent_hyderabad_house",
                 r"rent_hyderabad_nb_building_new"]


def _extract(html):
    seen = dict.fromkeys(BASE + m for m in DETAIL_RE.findall(html))
    return list(seen)


def urls(fetcher, done=frozenset(), include_rent=False, **_):
    patterns = SALE_SITEMAPS + (RENT_SITEMAPS if include_rent else [])
    index = sitemap_locs(fetcher, SITEMAP_INDEX)
    for pattern in patterns:
        for sitemap in (u for u in index if re.search(pattern, u)):
            pages = sitemap_locs(fetcher, sitemap)
            yield from crawl_listing_pages(fetcher, done, pages, _extract)


def parse(url, raw):
    t = to_text(raw)
    kind = "Rent" if "/property/rent/" in url else "Sale"
    slug = url.split("/")[-3]
    price = money(first(r"(?:READY|UNDER CONSTRUCTION|NEW LAUNCH|RESALE)?\s*₹\s*([\d.,]+\s*(?:Cr|Crore|Lacs?|Lakhs?|K)?)", t))
    if not price:
        price = money(first(r"for Rs\.\s*([\d,]+)", t))
    area_m = re.search(r"(Builtup|Carpet|Super Builtup|Plot|Super Built Up|Built Up)\s+Area\s+([\d,.]+)\s*(sq\.?\s?ft|sq\.?\s?yard|sq\.?\s?m)", t, re.I)
    if area_m:
        unit = area_m.group(3).lower().replace(" ", "")
        area = num(area_m.group(2)) * SQFT_PER.get("sq.yards" if "yard" in unit else "sq.meter" if unit.endswith("m") else "sq.ft", 1)
    else:
        area = num(first(r"([\d,.]+)\s*Sq\.?\s?Ft", t, flags=re.I))
    if not (price or area):
        return None

    floors = re.search(r"No\. of Floors\s+(\d+|NA)\s*/\s*(\d+)", t)
    age = first(r"Age of Building\s+(.+?)\s+(?:Ownership Type|Maintenance)", t)
    age_years = 0.0 if re.search(r"new|under", age, re.I) else num(age)
    raw_loc = next(iter(re.findall(r'"locality"\s*:\s*"([^"]+)"', raw)), "")
    parts = [x.strip() for x in raw_loc.split(",")]
    state_at = next((i for i, x in enumerate(parts) if re.match(r"(Telangana|Andhra)", x)), None)
    if state_at:  # a full postal address: take the area just before the state, and its pincode
        locality = parts[state_at - 1]
    else:
        locality = raw_loc or first(r"-for-(?:sale|rent)-in-(.+?)-hyderabad", slug + "-hyderabad").replace("-", " ").title()
    pincode = first(r"\b(5\d{5})\b", raw_loc)
    society = first(r"(?:Flat|House|Villa|Apartment|Plot|Land|Penthouse)s? for (?:Sale|Rent) in (.+?), Hyderabad", t)
    bhk = first(r"^(\d+(?:\.\d)?)-bhk", slug)
    lat = first(r'"(?:latitude|lat)"\s*:\s*"?([\d.]+)', raw)
    lon = first(r'"(?:longitude|lon|lng)"\s*:\s*"?([\d.]+)', raw)
    ptype = first(r"-bhk-(.+?)-for-", slug) or first(r"^(.+?)-for-", slug)
    possession = first(r"No\. of Bathroom\s+(.+?)\s+Possession", t)

    return base_row(url, SOURCE, price, area, dict(
        BHK=bhk or first(r"(\d+)\s*Bedroom", t), Bathrooms=num(first(r"(\d+)\s*Bathroom\s+No\. of Bathroom", t)) or "",
        Floor_Number=floors.group(1) if floors and floors.group(1) != "NA" else "",
        Total_Floors=floors.group(2) if floors else "",
        Property_Age_Years=age_years if age_years is not None else "", Age_Group="10+ Years" if age.startswith(">") else age_group(age_years),
        Locality=locality, Pincode=pincode, Society=society, Furnishing=first(r"Furnishing Status\s+(\w+(?: \w+)?)\s+Facing", t),
        Facing=first(r"Facing\s+([A-Za-z -]+?)\s+No\. of Floors", t),
        Ownership=first(r"Ownership Type\s+(.+?)\s+Maintenance", t),
        Car_Parking=first(r"Parking\s+(\w+)\s+Gated", t),
        Construction_Status=first(r"(READY|UNDER CONSTRUCTION)", t).title() or possession,
        Transaction="Resale" if "Resale" in t[:600] else kind,
        Latitude=lat, Longitude=lon, Listing_Type=kind, Property_Type=ptype.replace("-", " ").title(),
        Full_Address=", ".join(x for x in (society, locality, "Hyderabad", "India") if x),
        Posted_On=first(r"([A-Z][a-z]{2} \d{1,2}, \d{4})\s+Posted On", t),
    ))
