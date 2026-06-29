"""CLI entry for sloane ingest runners.

Usage:
  python -m sloane.ingest samehadaku              # 2h feed-delta ingest
  python -m sloane.ingest samehadaku --discover   # daily new-series sweep
  python -m sloane.ingest samehadaku --max-new 5  # smoke cap

Prints JSON result to stdout (journald captures it under systemd).
"""
from __future__ import annotations
import argparse
import json
import sys

from sloane.ingest.samehadaku import ingest_feed, discover_new_series


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="sloane-ingest")
    p.add_argument("source", choices=["samehadaku"])
    p.add_argument("--discover", action="store_true",
                   help="run new-series discovery instead of feed ingest")
    p.add_argument("--max-new", type=int, default=None,
                   help="cap new items ingested (smoke)")
    args = p.parse_args(argv)

    if args.source == "samehadaku":
        if args.discover:
            result = discover_new_series(max_new=args.max_new)
        else:
            result = ingest_feed(max_new=args.max_new)
    else:
        p.error(f"unknown source {args.source}")
        return 2

    print(json.dumps(result, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
