"""Run the full pipeline on a schedule (no extra dependencies).

    python -m konu.scheduler --every 24 --limit 5000        # every 24 h, up to 5000 new pages per site per run
    python -m konu.scheduler --at 02:30 --limit 0            # daily at 02:30 local time, no page cap
    python -m konu.scheduler --once                          # a single run (for cron / systemd timers)

Each run crawls where the previous one stopped (state is checkpointed), so a capped schedule
gradually covers whole sites. A lock file prevents overlapping runs, a failed run is logged and the
schedule keeps going, and everything is logged to logs/pipeline.log (rotated).
"""
import argparse
import logging
import os
import signal
import sys
import time
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler

from .crawl import crawl
from .pipeline import build_final
from .schema import LOG_DIR, ROOT
from .sources import LIVE_SOURCES

LOCK_FILE = ROOT / "data" / "interim" / ".pipeline.lock"
log = logging.getLogger("konu.scheduler")


def _setup_logging():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    handlers = [RotatingFileHandler(LOG_DIR / "pipeline.log", maxBytes=5_000_000, backupCount=5),
                logging.StreamHandler(sys.stderr)]
    for h in handlers:
        h.setFormatter(fmt)
        log.addHandler(h)
    log.setLevel(logging.INFO)


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


class RunLock:
    """Exclusive lock file holding our PID; a stale lock from a dead process is taken over."""

    def __enter__(self):
        LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
        if LOCK_FILE.exists():
            try:
                pid = int(LOCK_FILE.read_text().strip())
            except ValueError:
                pid = 0
            if pid and _pid_alive(pid):
                raise RuntimeError(f"another run is active (pid {pid})")
        LOCK_FILE.write_text(str(os.getpid()))
        return self

    def __exit__(self, *exc):
        LOCK_FILE.unlink(missing_ok=True)


def run_once(args):
    """One crawl + merge + enrich cycle. Never raises: returns True on success."""
    try:
        with RunLock():
            started = time.time()
            log.info("run started: sources=%s limit=%s", args.sources, args.limit)
            results = crawl(args.sources, args.limit, args.delay, args.include_rent)
            for name, (parsed, failed) in results.items():
                log.info("  %-16s parsed=%d failed/skipped=%d", name, parsed, failed)
            df = build_final()
            log.info("run finished in %.0f s: %d rows in final CSV", time.time() - started, len(df))
        return True
    except RuntimeError as exc:
        log.warning("skipped: %s", exc)
    except Exception:
        log.exception("run failed; the schedule will try again next time")
    return False


def next_run(args, now):
    if args.at:
        hour, minute = map(int, args.at.split(":"))
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        return target if target > now else target + timedelta(days=1)
    return now + timedelta(hours=args.every)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--every", type=float, default=24, help="hours between runs (default 24)")
    ap.add_argument("--at", help="run daily at HH:MM local time instead of every N hours")
    ap.add_argument("--once", action="store_true", help="run a single cycle and exit")
    ap.add_argument("--no-initial-run", action="store_true", help="wait for the first scheduled time")
    ap.add_argument("--sources", default=",".join(LIVE_SOURCES))
    ap.add_argument("--limit", type=int, default=5000, help="max new pages per site per run (0 = unlimited)")
    ap.add_argument("--delay", type=float, default=1.0, help="seconds between requests to one site")
    ap.add_argument("--include-rent", action="store_true")
    args = ap.parse_args(argv)
    args.sources = [s.strip() for s in args.sources.split(",")]

    _setup_logging()
    if args.once:
        sys.exit(0 if run_once(args) else 1)

    stop = []
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.append(1))
    if not args.no_initial_run:
        run_once(args)
    while not stop:
        when = next_run(args, datetime.now())
        log.info("next run at %s", when.strftime("%Y-%m-%d %H:%M"))
        while not stop and datetime.now() < when:
            time.sleep(min(30, max(1, (when - datetime.now()).total_seconds())))
        if not stop:
            run_once(args)
    log.info("scheduler stopped")


if __name__ == "__main__":
    main()
