"""Live crawlers. Each source exposes `urls(fetcher, **opts)` and `parse(url, raw)`."""
from . import proptiger, realestateindia

LIVE_SOURCES = {
    "realestateindia": realestateindia,
    "proptiger": proptiger,
}
