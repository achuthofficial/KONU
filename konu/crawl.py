"""Stage 1: crawl live sources into an interim CSV (resumable, polite)."""
import csv
import json
import sys

from .http import Fetcher
from .schema import COLUMNS, CRAWLED_CSV, STATE_FILE
from .sources import LIVE_SOURCES


def _log(msg):
    print(msg, file=sys.stderr, flush=True)


def crawl(sources, limit=100, delay=1.0, include_rent=False, out=CRAWLED_CSV, state_file=STATE_FILE):
    """Fetch up to `limit` new pages per source (0 = unlimited) and append rows to `out`."""
    fetcher = Fetcher(delay=delay, log=_log)
    done = set(json.loads(state_file.read_text())) if state_file.exists() else set()
    out.parent.mkdir(parents=True, exist_ok=True)
    new_file = not out.exists()

    def checkpoint():
        handle.flush()
        state_file.write_text(json.dumps(sorted(done)))

    with open(out, "a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, extrasaction="ignore")
        if new_file:
            writer.writeheader()
        for name in sources:
            module = LIVE_SOURCES[name]
            parsed = failed = 0
            for url in module.urls(fetcher, include_rent=include_rent):
                if url in done:
                    continue
                if limit and parsed + failed >= limit:
                    break
                raw = fetcher.get(url)
                done.add(url)
                row = module.parse(url, raw) if raw else None
                if row:
                    writer.writerow(row)
                    parsed += 1
                else:
                    failed += 1
                if (parsed + failed) % 25 == 0:
                    checkpoint()
                    _log(f"[{name}] parsed={parsed} failed={failed}")
            checkpoint()
            _log(f"[{name}] finished: parsed={parsed} failed/skipped={failed}")
