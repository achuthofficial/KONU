"""Stage 1: crawl live sources into an interim CSV (parallel across sites, resumable, polite).

Each site runs in its own thread with its own rate limiter, so total speed scales with the number
of sites while each individual host still sees at most one request per `delay` seconds.
"""
import csv
import json
import sys
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor

from .http import Fetcher
from .schema import COLUMNS, CRAWLED_CSV, STATE_DIR
from .sources import LIVE_SOURCES


def _log(msg):
    print(msg, file=sys.stderr, flush=True)


def _load_state(path):
    return set(json.loads(path.read_text())) if path.exists() else set()


def _crawl_one(name, writer, write_lock, limit, delay, include_rent, state_dir):
    """Crawl a single site; returns (parsed, failed)."""
    module = LIVE_SOURCES[name]
    state_path = state_dir / f"{name}.json"
    done = _load_state(state_path)
    fetcher = Fetcher(delay=delay, log=lambda m: _log(f"[{name}] {m}"))
    parsed = failed = 0

    def checkpoint():
        state_path.write_text(json.dumps(sorted(done)))

    try:
        for url in module.urls(fetcher, done=done, include_rent=include_rent):
            if url in done:
                continue
            if limit and parsed + failed >= limit:
                break
            raw = fetcher.get(url)
            row = None
            if raw:
                try:
                    row = module.parse(url, raw)
                except Exception:  # one odd page must not stop the whole crawl
                    _log(f"[{name}] parse error on {url}\n{traceback.format_exc(limit=2)}")
            if raw is not None:
                done.add(url)  # fetch errors (None) are retried next run; unparseable pages are not
            if row:
                with write_lock:
                    writer.writerow(row)
                parsed += 1
            else:
                failed += 1
            if (parsed + failed) % 25 == 0:
                with write_lock:
                    writer.handle.flush()
                checkpoint()
                _log(f"[{name}] parsed={parsed} failed={failed}")
    except Exception:
        _log(f"[{name}] crawler stopped on error:\n{traceback.format_exc(limit=4)}")
    finally:
        checkpoint()
    _log(f"[{name}] finished: parsed={parsed} failed/skipped={failed}")
    return parsed, failed


class _Writer:
    def __init__(self, handle):
        self.handle = handle
        self._csv = csv.DictWriter(handle, fieldnames=COLUMNS, extrasaction="ignore")

    def writeheader(self):
        self._csv.writeheader()

    def writerow(self, row):
        self._csv.writerow(row)


def _migrate_header(path):
    """Rewrite an interim CSV written under an older column set so appended rows line up."""
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames == COLUMNS:
            return
        rows = list(reader)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, extrasaction="ignore", restval="")
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(path)
    _log(f"migrated {path.name} to the current column set ({len(rows)} rows)")


def crawl(sources, limit=100, delay=1.0, include_rent=False, out=CRAWLED_CSV, state_dir=STATE_DIR):
    """Fetch up to `limit` new pages per source (0 = unlimited) and append rows to `out`."""
    out.parent.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)
    new_file = not out.exists()
    if not new_file:
        _migrate_header(out)
    write_lock = threading.Lock()
    results = {}
    with open(out, "a", newline="", encoding="utf-8") as handle:
        writer = _Writer(handle)
        if new_file:
            writer.writeheader()
        with ThreadPoolExecutor(max_workers=max(1, len(sources))) as pool:
            futures = {name: pool.submit(_crawl_one, name, writer, write_lock, limit, delay, include_rent, state_dir)
                       for name in sources}
            for name, future in futures.items():
                results[name] = future.result()
    return results
