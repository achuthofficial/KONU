"""proptiger.com new-project pages (one row per project)."""
import json
import re

from ..parsing import base_row, money, num, to_text

SOURCE = "proptiger.com"
SITEMAP_INDEX = "https://www.proptiger.com/secure-sitemap-index.xml"
LD_TYPES = ("ApartmentComplex", "Residence", "Apartment")


def urls(fetcher, **_):
    for sitemap in re.findall(r"<loc>([^<]+)</loc>", fetcher.get(SITEMAP_INDEX) or ""):
        if re.search(r"secure-sitemap-project(-\d+)?\.xml", sitemap):
            for url in re.findall(r"<loc>([^<]+)</loc>", fetcher.get(sitemap) or ""):
                if "/hyderabad/" in url:
                    yield url


def _json_ld(raw):
    for block in re.findall(r"ld\+json[^>]*>(.*?)</script>", raw, re.S):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("@type") in LD_TYPES:
            return data
    return None


def parse(url, raw):
    ld = _json_ld(raw)
    if not ld:
        return None
    text = to_text(raw)
    k = text.find("(show on map)")
    head = text[k: k + 900] if k >= 0 else text
    pre = text[max(0, k - 200): k] if k >= 0 else ""

    price_rng = re.search(r"₹\s*([\d.,]+\s*(?:Cr|L|Lac))\s*(?:-\s*₹\s*([\d.,]+\s*(?:Cr|L|Lac)))?", head)
    config = re.search(r"Configuration\s+([\d.,\s/]+(?:BHK|RK)?[^A-Za-z]*(?:BHK|RK)?)", head)
    area_rng = re.search(r"sq ft\s+([\d,]+)\s*(?:-\s*([\d,]+))?\s*sq ft", head)
    avg = re.search(r"Avg\. Price\s*₹\s*([\d,]+)", head)
    possession = re.search(r"Possession\s*:?\s*([A-Za-z]{3}'\d{2})", text)
    status = re.search(r"Possession Status\s+([A-Za-z ]+?)\s+(?:Avg|Price)", head)
    rera = re.search(r"RERA ID\s+([A-Z0-9/\-]+)", text)
    address = ld.get("address", {})
    builder = re.search(r"\bby\s+(.+?)\s+" + re.escape(address.get("addressLocality", "").split(",")[0]) + r",", pre)
    geo = ld.get("geo", {})
    locality = address.get("addressLocality", "").replace(", Hyderabad", "")

    pmin = money(price_rng.group(1)) if price_rng else None
    pmax = money(price_rng.group(2)) if price_rng and price_rng.group(2) else None
    amin = num(area_rng.group(1)) if area_rng else None
    amax = num(area_rng.group(2)) if area_rng and area_rng.group(2) else None
    bhks = re.findall(r"\d(?:\.\d)?", config.group(1)) if config else []

    row = base_row(url, SOURCE, pmin, amin, dict(
        BHK="/".join(bhks), Locality=locality, Society=ld.get("name", ""), Transaction="New Property",
        Construction_Status=(status.group(1).strip() if status else "") or (possession.group(1) if possession else ""),
        Latitude=geo.get("latitude", ""), Longitude=geo.get("longitude", ""),
        Full_Address=", ".join(x for x in (ld.get("name"), locality, "Hyderabad", "India") if x),
        Listing_Type="Sale", Property_Type=ld.get("@type", ""), Price_Max_INR=round(pmax) if pmax else "",
        Area_Max_Sqft=amax or "", Builder=builder.group(1) if builder else "", RERA_ID=rera.group(1) if rera else "",
    ))
    if avg:
        row["PricePerSqft"] = float(avg.group(1).replace(",", ""))
    return row if (pmin or amin) else None
