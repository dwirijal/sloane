"""sloane worker: ingest loop + HTTP kick server on :8081.

Runs ensure_schema once at startup, then loops: per-source ingest (try/except
one failed source doesn't kill container), then wait on Event for interval or
until POST /run kicks. Stdlib http.server (no async juggling with blocking
ingest). ponytail: no connection pool — one psycopg.connect per ingest call
(matches existing writer/merger pattern). Add pool when throughput matters.
"""
from __future__ import annotations
import json
import os
import threading
import logging
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

from sloane.db import ensure_schema
from sloane.ingest.samehadaku import ingest_feed
from sloane.ingest.anichin import ingest_updates as ingest_anichin

log = logging.getLogger("sloane.worker")
logging.basicConfig(level=logging.INFO, format='{"ts":"%(asctime)s","msg":"%(message)s"}')
DSN = os.environ.get("DOS_PGB_URL")
SOURCES = os.environ.get("SLOANE_SOURCES", "samehadaku anichin").split()
INTERVAL = int(os.environ.get("SLOANE_INTERVAL_SECONDS", "86400"))
wake = threading.Event()


def run_ingest(src: str) -> dict:
    """One delta cycle for a source. Returns result dict."""
    if src == "samehadaku":
        return ingest_feed(max_new=None)
    if src == "anichin":
        return ingest_anichin(max_new=None)
    raise ValueError(f"unknown source {src}")


class KickHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == "/run":
            wake.set()
            self.send_response(202); self.end_headers()
            self.wfile.write(b'{"sync":"queued"}')
        else:
            self.send_response(404); self.end_headers()

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200); self.end_headers()
            self.wfile.write(b'{"ok":true}')
        else:
            self.send_response(404); self.end_headers()

    def log_message(self, *a):
        pass  # silence default access log


def serve_kicks():
    ThreadingHTTPServer(("0.0.0.0", 8081), KickHandler).serve_forever()


def main() -> int:
    if not DSN:
        log.error("DOS_PGB_URL unset"); return 2
    ensure_schema(DSN)  # idempotent; safe on every startup
    threading.Thread(target=serve_kicks, daemon=True).start()
    log.info(f"worker up sources={SOURCES} interval={INTERVAL}")
    while True:
        for src in SOURCES:
            try:
                r = run_ingest(src)
                log.info(json.dumps({"source": src, "result": r}, default=str))
            except Exception as e:
                log.error(json.dumps({"source": src, "error": str(e)}))
        wake.clear()
        wake.wait(timeout=INTERVAL)  # blocks until interval or POST /run
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
