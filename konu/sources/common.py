"""Helpers shared by the site crawlers."""
import json
import re

LOC_RE = re.compile(r"<loc>([^<]+)</loc>")


def sitemap_locs(fetcher, url):
    """All <loc> entries of a sitemap or sitemap index (handles .gz)."""
    return LOC_RE.findall(fetcher.get(url) or "")


def ld_json(raw):
    """Every parseable JSON-LD block on the page, flattened out of any @graph."""
    nodes = []
    for block in re.findall(r"ld\+json[^>]*>(.*?)</script>", raw, re.S):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        for item in data if isinstance(data, list) else [data]:
            nodes.extend(item.get("@graph", [item]) if isinstance(item, dict) else [])
    return nodes


def has_type(node, *types):
    kind = node.get("@type")
    kinds = kind if isinstance(kind, list) else [kind]
    return any(t in kinds for t in types)


def first(pattern, text, group=1, flags=0):
    """First regex group or ''."""
    m = re.search(pattern, text, flags)
    return m.group(group).strip() if m else ""


def crawl_listing_pages(fetcher, done, pages, extract):
    """Yield detail URLs found on index pages, marking a page done only once all its links were yielded.

    `extract(html)` returns the detail URLs on a page. Pages already in `done` are skipped, so an
    interrupted crawl resumes without re-reading them.
    """
    for page in pages:
        if page in done:
            continue
        html = fetcher.get(page)
        for url in extract(html or ""):
            yield url
        done.add(page)
