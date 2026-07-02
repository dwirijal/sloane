"""CLI entry for sloane ingest runners.

Usage:
  python -m sloane.ingest samehadaku              # 2h feed-delta ingest
  python -m sloane.ingest samehadaku --discover   # daily new-series sweep
  python -m sloane.ingest samehadaku --backfill   # full historical ingest
  python -m sloane.ingest anichin                 # 2h latest-update delta ingest
  python -m sloane.ingest anichin --discover      # daily A-Z new-series sweep
  python -m sloane.ingest anichin --backfill      # full historical ingest
  python -m sloane.ingest <source> --max-new 5    # smoke cap

Prints JSON result to stdout (journald captures it under systemd).
"""
from __future__ import annotations
import argparse
import json
import os
import sys

from sloane.ingest.samehadaku import ingest_feed, discover_new_series as discover_samehadaku, backfill_all as backfill_samehadaku
from sloane.ingest.anichin import ingest_updates as ingest_anichin, discover_new_series as discover_anichin, backfill_all as backfill_anichin


def _pos_int(name):
    """argparse type for --workers: reject <=0 at the trust boundary (Semaphore
    would otherwise raise ValueError mid-backfill)."""
    def parse(v):
        n = int(v)
        if n < 1:
            raise argparse.ArgumentTypeError(f"{name} must be >= 1, got {n}")
        return n
    return parse


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="sloane-ingest")
    p.add_argument("source", choices=["samehadaku", "anichin"])
    g = p.add_mutually_exclusive_group()
    g.add_argument("--discover", action="store_true",
                   help="run new-series discovery instead of delta ingest")
    g.add_argument("--backfill", action="store_true",
                   help="full historical ingest (all series + all episodes)")
    p.add_argument("--max-new", type=int, default=None,
                   help="cap new items ingested (smoke); for --backfill caps series count")
    p.add_argument("--workers", type=_pos_int("workers"), default=6,
                   help="concurrency for --backfill (default 6, must be >= 1)")
    args = p.parse_args(argv)

    # DOS_PGB_URL guard: pg_dsn() (shared/config.py) silently falls back to a
    # stale default password + wrong DB when this is unset. Fail loud at CLI
    # entry instead. After parse_args so --help still works.
    # ponytail: lift to shared/config.py when upstream drops the hardcoded default.
    if not os.environ.get("DOS_PGB_URL"):
        sys.stderr.write("DOS_PGB_URL unset; set in ~/.config/sloane/ingest.env\n")
        return 2

    if args.source == "samehadaku":
        if args.backfill:
            result = backfill_samehadaku(workers=args.workers, limit=args.max_new)
        elif args.discover:
            result = discover_samehadaku(max_new=args.max_new)
        else:
            result = ingest_feed(max_new=args.max_new)
    elif args.source == "anichin":
        if args.backfill:
            result = backfill_anichin(workers=args.workers, limit=args.max_new)
        elif args.discover:
            result = discover_anichin(max_new=args.max_new)
        else:
            result = ingest_anichin(max_new=args.max_new)
    else:
        p.error(f"unknown source {args.source}")
        return 2

    print(json.dumps(result, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
