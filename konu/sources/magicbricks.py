"""magicbricks.com project pages (one row per project) for Hyderabad."""
import re

from ..parsing import base_row, num, to_text
from .common import first, has_type, ld_json, sitemap_locs

SOURCE = "magicbricks.com"
SITEMAP_INDEX = "https://www.magicbricks.com/sitemap_index.xml"


def urls(fetcher, **_):
    for sitemap in (u for u in sitemap_locs(fetcher, SITEMAP_INDEX) if re.search(r"/pdp_Hyderabad\d*\.xml", u)):
        for url in sitemap_locs(fetcher, sitemap):
            if "-pdpid-" in url:
                yield url


def parse(url, raw):
    product = next((n for n in ld_json(raw) if has_type(n, "Residence", "Product")), None)
    if not product:
        return None
    offers = product.get("offers") or {}  # projects without a published price have no offers block
    offer = offers[0] if isinstance(offers, list) else offers
    low, high = num(str(offer.get("lowPrice", ""))), num(str(offer.get("highPrice", "")))
    address, geo = product.get("address", {}), product.get("geo", {})
    rating = product.get("aggregateRating", {})
    t = to_text(raw)
    name = product.get("name", "")
    status = first(re.escape(name) + r"\s+Status\s*([A-Za-z ]+?)(?:\s{1}[A-Z][a-z]+ [a-z]+ |\s+is\s|\.|$)", t)
    status = next((s for s in ("Ready To Move", "Under Construction", "New Launch") if s.lower() in status.lower()), status)
    locality = address.get("addressLocality", "")
    area_unit = first(r"around Rs\.\s*([\d,]+)/sq\. ft", t)

    row = base_row(url, SOURCE, low, None, dict(
        Locality=locality, Society=name, Pincode=address.get("postalCode", ""),
        Latitude=geo.get("latitude", ""), Longitude=geo.get("longitude", ""),
        Construction_Status=status, Transaction="New Property", Listing_Type="Sale",
        Property_Type="Project", Price_Max_INR=round(high) if high else "",
        Total_Units=num(first(r"Total Units\s+(\d+)", t)) or "",
        Rating=rating.get("ratingValue", ""), Review_Count=rating.get("reviewCount", ""),
        PricePerSqft=num(area_unit) or "",
        Full_Address=address.get("streetAddress", "") or ", ".join(x for x in (name, locality, "Hyderabad") if x),
    ))
    return row if (low or name) else None
