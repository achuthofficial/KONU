"""Live crawlers. Each source exposes `urls(fetcher, done, include_rent)` and `parse(url, raw)`."""
from . import magicbricks, nobroker, proptiger, realestateindia, squareyards

LIVE_SOURCES = {
    "nobroker": nobroker,
    "magicbricks": magicbricks,
    "squareyards": squareyards,
    "realestateindia": realestateindia,
    "proptiger": proptiger,
}
