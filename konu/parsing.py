"""Small text/number helpers shared by the site parsers."""
import html
import re
from datetime import date

from .schema import COLUMNS

SQFT_PER = {"sq.ft.": 1, "sq.ft": 1, "sq. yards": 9, "sq.yards": 9, "sq. meter": 10.7639, "sq.meter": 10.7639,
            "acre": 43560, "cent": 435.6, "guntha": 1089, "ares": 1076.39, "hectares": 107639}


def to_text(raw):
    """Strip scripts, styles and tags from HTML and collapse whitespace."""
    unescaped = html.unescape(raw)
    text = re.sub(r"<script.*?</script>|<style.*?</style>|<[^>]+>", " ", unescaped, flags=re.S)
    return re.sub(r"\s+", " ", text)


def money(s):
    """'1.5 Cr' / '68 Lac' / '2.00 L' / '₹ 5,000' -> rupees (float) or None."""
    if not s:
        return None
    m = re.search(r"([\d,]+(?:\.\d+)?)\s*(Crores?|Cr|Lacs?|Lakhs?|L|K)?\b", s.replace("₹", " "), re.I)
    if not m:
        return None
    value = float(m.group(1).replace(",", ""))
    unit = (m.group(2) or "").lower()
    multiplier = {"cr": 1e7, "crore": 1e7, "crores": 1e7, "lac": 1e5, "lacs": 1e5, "lakh": 1e5, "lakhs": 1e5,
                  "l": 1e5, "k": 1e3}.get(unit, 1)
    return value * multiplier


def num(s):
    m = re.search(r"[\d,]+(?:\.\d+)?", s or "")
    return float(m.group(0).replace(",", "")) if m else None


def age_group(years):
    if years is None:
        return ""
    return "New" if years <= 1 else "1-5 Years" if years <= 5 else "6-10 Years" if years <= 10 else "10+ Years"


def base_row(url, source, price, area, extra=None):
    """An empty schema row pre-filled with source, date, and derived price fields."""
    today = date.today()
    row = {c: "" for c in COLUMNS}
    row.update(URL=url, Source=source, Year=today.year, Month=today.month, YearMonth=today.strftime("%Y-%m"))
    if price:
        row["Price_INR"] = round(price)
        row["Price_Cr"] = round(price / 1e7, 4)
    if area:
        row["Area_Sqft"] = round(area, 2)
        if price:
            row["PricePerSqft"] = round(price / area, 2)
    row.update(extra or {})
    return row
