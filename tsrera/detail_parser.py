"""Parse a TS RERA PrintPreview detail page into structured fields.

The page is a long ASP.NET form of labelled read-only inputs grouped under
section headings (General Information, Project Information, Land Details, ...).
We recover it generically: walk each heading, then collect the label/value
pairs and any tables that follow it, so new fields survive without code changes.
"""

from __future__ import annotations

import re
from bs4 import BeautifulSoup, Tag

SECTION_TAGS = {"h1", "h2", "h3", "h4", "h5", "legend"}
# Section titles seen on the reference page; used only to order output nicely.
KNOWN_ORDER = [
    "General Information",
    "Address For Official Communication",
    "Contact Details",
    "Project Information",
    "Bank Details",
    "Land Details",
    "Address Details",
    "Development Work",
    "Building Details",
    "Project Professional Information",
    "Uploaded Orders",
]


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def _field_value(el: Tag) -> str:
    """A displayed value: input/textarea value, else element text."""
    if el.name in ("input", "textarea"):
        return _clean(el.get("value") or el.get_text(" "))
    return _clean(el.get_text(" "))


def _table_to_rows(table: Tag) -> list[dict]:
    heads = [_clean(th.get_text(" ")) for th in table.find_all("th")]
    rows = []
    for tr in table.find_all("tr"):
        cells = tr.find_all("td")
        if not cells:
            continue
        vals = [_field_value(td) for td in cells]
        if heads and len(heads) == len(vals):
            rows.append(dict(zip(heads, vals)))
        else:
            rows.append({f"col{i}": v for i, v in enumerate(vals)})
    return rows


def _label_value(lab: Tag, soup: BeautifulSoup) -> str:
    """Resolve the value shown next to a label.

    The detail page lays fields out on a Bootstrap grid: the <label> sits in one
    column div and the human-readable value is the text of the NEXT sibling
    column div. A hidden input holding the coded value usually follows; we prefer
    the visible text and fall back to the input only when there is no text.
    """
    # 1) Bootstrap-grid: parent column div -> next sibling column div's text.
    col = lab.find_parent("div")
    if col is not None:
        sib = col.find_next_sibling("div")
        while sib is not None:
            txt = _clean(sib.get_text(" "))
            if txt:
                return txt
            sib = sib.find_next_sibling("div")

    # 2) Classic label[for] -> field (only if it carries a visible value).
    tgt = lab.get("for")
    if tgt:
        node = soup.find(id=tgt)
        if node is not None:
            v = _field_value(node)
            if v:
                return v

    # 3) label / value in adjacent table cells.
    td = lab.find_parent("td")
    if td and td.find_next_sibling("td"):
        return _field_value(td.find_next_sibling("td"))
    return ""


def _harvest_pairs(scope: Tag, soup: BeautifulSoup) -> dict:
    out: dict[str, str] = {}
    for lab in scope.find_all("label"):
        key = _clean(lab.get_text(" "))
        if not key or key.lower() == "select":
            continue
        val = _label_value(lab, soup)
        if key and val and val.lower() != key.lower():
            out.setdefault(key, val)
    return out


def parse_detail(html: str) -> dict:
    """Return {"sections": {name: {...}}, "tables": {name: [rows]}, "raw_labels": {...}}."""
    soup = BeautifulSoup(html, "html.parser")

    # Drop non-content noise.
    for bad in soup.select("script, style, noscript"):
        bad.decompose()

    sections: dict[str, dict] = {}
    tables: dict[str, list] = {}

    headings = [
        h for h in soup.find_all(list(SECTION_TAGS)) if _clean(h.get_text(" "))
    ]

    for i, h in enumerate(headings):
        name = _clean(h.get_text(" "))
        if not name:
            continue
        stop = headings[i + 1] if i + 1 < len(headings) else None

        # Walk forward from this heading to the next, collecting label/value
        # pairs and any tables that belong to this section.
        pairs: dict[str, str] = {}
        tbls: list[dict] = []
        seen_tables: set[int] = set()
        node = h
        while True:
            node = node.find_next()
            if node is None or node is stop:
                break
            if not isinstance(node, Tag):
                continue
            if node.name == "table" and id(node) not in seen_tables:
                seen_tables.add(id(node))
                tbls.extend(_table_to_rows(node))
            elif node.name == "label":
                key = _clean(node.get_text(" "))
                if key and key.lower() != "select":
                    val = _label_value(node, soup)
                    if val and val.lower() != key.lower():
                        pairs.setdefault(key, val)

        if pairs:
            sections[name] = pairs
        if tbls:
            tables[name] = tbls

    # Global label sweep as a safety net for anything missed by sectioning.
    raw = _harvest_pairs(soup, soup)

    ordered = {k: sections[k] for k in KNOWN_ORDER if k in sections}
    for k, v in sections.items():
        ordered.setdefault(k, v)

    return {"sections": ordered, "tables": tables, "raw_labels": raw}


if __name__ == "__main__":
    import json
    import sys

    data = parse_detail(open(sys.argv[1], encoding="utf-8", errors="replace").read())
    print(json.dumps(data, indent=2, ensure_ascii=False)[:4000])
