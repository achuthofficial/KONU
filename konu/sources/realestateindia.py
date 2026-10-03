"""realestateindia.com listing pages (resale/new/rent flats, houses, plots)."""
import re

from ..parsing import age_group, base_row, money, num, to_text, SQFT_PER

SOURCE = "realestateindia.com"
SITEMAP_INDEX = "https://www.realestateindia.com/sitemap_index.xml"

KEYS = ["Listing Type", "Building Type", "Property Type", "City", "Locality", "Price", "Number of Rooms",
        "Balcony", "Number of Bathroom", "Built Up Area", "Carpet Area", "Super Area", "Plot/Land Area",
        "Plot Area", "Ownership", "Sale Type", "Age of Property", "Project & Society", "Floor Number",
        "Total Floor Count", "Power Back-up", "Booking Amount", "Maintenance Charge", "Furnishing", "Facing",
        "Status", "Amenities", "Location & Connectivity"]
AREA_UNIT = r"[\d.,]+\s*(Sq\.?\s?(?:ft|Yards|Meter)\.?|Acre|Cent|Guntha|Ares|Hectares)"


def urls(fetcher, include_rent=False):
    kinds = ("property-detail-buy",) + (("property-detail-rent",) if include_rent else ())
    for sitemap in re.findall(r"<loc>([^<]+)</loc>", fetcher.get(SITEMAP_INDEX) or ""):
        if not any(k in sitemap for k in kinds):
            continue
        for url in re.findall(r"<loc>([^<]+)</loc>", fetcher.get(sitemap) or ""):
            if "hyderabad" not in url.split("/")[-1]:
                continue
            if re.search(r"flat|apartment|villa|house|floor|penthouse|studio|plot|land", url) and \
                    not re.search(r"agricultur|farm|commercial|office|shop|warehouse|godown", url):
                yield url


def _key_values(text):
    seg = text[text.find("Property Information"):]
    hits = []
    for key in KEYS:
        m = re.search(r"(?<![A-Za-z])" + re.escape(key) + r"(?![A-Za-z])", seg)
        if m:
            hits.append((m.start(), key, m.end()))
    hits.sort()
    return {key: seg[end: hits[i + 1][0] if i + 1 < len(hits) else len(seg)].strip()
            for i, (_, key, end) in enumerate(hits)}


def parse(url, raw):
    text = to_text(raw)
    if "Property Information" not in text:
        return None
    kv = _key_values(text)
    if kv.get("Listing Type", "").split(" ")[0] not in ("Sale", "Rent", "Lease"):
        return None

    price = money(kv.get("Price"))
    area_txt = (kv.get("Built Up Area") or kv.get("Super Area") or kv.get("Carpet Area")
                or kv.get("Plot/Land Area") or kv.get("Plot Area") or "")
    area = num(area_txt)
    unit_match = re.search(AREA_UNIT, area_txt, re.I)
    unit = re.sub(r"\s+", " ", (unit_match.group(1) if unit_match else "Sq.ft.").lower()).replace("sq. ft", "sq.ft")
    area = area * SQFT_PER.get(unit, 1) if area else None

    name = re.search(r'"name":\s*"([^"]*)"', raw)
    bhk = (re.search(r"(\d(?:\.\d)?)\s*BHK", (name.group(1) if name else "") + " " + url.replace("-", " "), re.I)
           or re.search(r"(\d(?:\.\d)?)\s*bkh", url, re.I))
    latlon = re.search(r'"latitude":\s*"?([\d.]+)"?,\s*"longitude":\s*"?([\d.]+)', raw)
    age = kv.get("Age of Property", "")
    age_years = 0.0 if "new" in age.lower() else num(age)
    locality = kv.get("Locality", "")
    society = kv.get("Project & Society", "")

    row = base_row(url, SOURCE, price, area, dict(
        BHK=bhk.group(1) if bhk else "", Bathrooms=num(kv.get("Number of Bathroom")) or "",
        Balconies=num(kv.get("Balcony")) or "", Floor_Number=kv.get("Floor Number", ""),
        Total_Floors=num(kv.get("Total Floor Count")) or "",
        Property_Age_Years=age_years if age_years is not None else "", Age_Group=age_group(age_years),
        Locality=locality, Society=society, Furnishing=kv.get("Furnishing", ""), Facing=kv.get("Facing", ""),
        Ownership=kv.get("Ownership", ""), Transaction=kv.get("Sale Type", "") or kv["Listing Type"],
        Construction_Status=kv.get("Status", ""),
        Latitude=latlon.group(1) if latlon else "", Longitude=latlon.group(2) if latlon else "",
        Full_Address=", ".join(x for x in (society, locality, "Hyderabad", "India") if x),
        Listing_Type=kv["Listing Type"].split(" ")[0], Property_Type=kv.get("Property Type", ""),
    ))
    return row if (price or area) else None
