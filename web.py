"""sloane read API (bare ASGI, uvicorn). Read-only via sloane_ro role.

POST /v1/sync kicks worker (HTTP POST to SLOANE_WORKER_URL/run); never writes.
ponytail: bare ASGI over FastAPI — 5 endpoints, no new heavy dep. Add FastAPI
if auth/middleware/validation complexity grows.
"""
from __future__ import annotations
import json
import os
import urllib.request
import urllib.error
import psycopg

DSN = os.environ["SLOANE_RO_PGB_URL"]  # fail loud at import; secret via env_file
WORKER = os.environ.get("SLOANE_WORKER_URL", "http://sloane-worker:8081")


async def _json(send, status, obj):
    b = json.dumps(obj, default=str).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [[b"content-type", b"application/json"]]})
    await send({"type": "http.response.body", "body": b})


def _entities(cur, kind=None, limit=50):
    if kind:
        cur.execute("SELECT id,kind,title,normalized_title FROM canonical_entities "
                    "WHERE kind=%s ORDER BY id DESC LIMIT %s", (kind, limit))
    else:
        cur.execute("SELECT id,kind,title,normalized_title FROM canonical_entities "
                    "ORDER BY id DESC LIMIT %s", (limit,))
    return [{"id": r[0], "kind": r[1], "title": r[2], "normalized_title": r[3]} for r in cur.fetchall()]


async def app(scope, receive, send):
    # ponytail: handle lifespan (uvicorn startup/shutdown) — respond so it
    # doesn't log "ASGI callable returned without starting response".
    if scope["type"] == "lifespan":
        while True:
            msg = await receive()
            if msg["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            elif msg["type"] == "lifespan.shutdown":
                await send({"type": "lifespan.shutdown.complete"})
                return
        return
    if scope["type"] != "http":
        return
    path, method = scope["path"], scope["method"]
    if path == "/v1/health" and method == "GET":
        await _json(send, 200, {"ok": True}); return
    if path == "/v1/entities" and method == "GET":
        qs = dict(p.split("=", 1) for p in scope["query_string"].decode().split("&") if "=" in p)
        kind = qs.get("kind"); limit = min(int(qs.get("limit", 50)), 200)
        with psycopg.connect(DSN) as conn, conn.cursor() as cur:
            await _json(send, 200, _entities(cur, kind, limit)); return
    if path.startswith("/v1/entities/") and method == "GET":
        try:
            cid = int(path.rsplit("/", 1)[-1])
        except ValueError:
            await _json(send, 404, {"error": "not found"}); return
        with psycopg.connect(DSN) as conn, conn.cursor() as cur:
            cur.execute("SELECT id,kind,title,normalized_title,best_payload FROM canonical_entities WHERE id=%s", (cid,))
            r = cur.fetchone()
            if not r:
                await _json(send, 404, {"error": "not found"}); return
            cur.execute("SELECT registry,external_id FROM external_ids WHERE canonical_id=%s", (cid,))
            ext = [{"registry": x[0], "external_id": x[1]} for x in cur.fetchall()]
            await _json(send, 200, {"id": r[0], "kind": r[1], "title": r[2], "normalized_title": r[3],
                                    "payload": r[4], "external_ids": ext}); return
    if path == "/v1/sources" and method == "GET":
        with psycopg.connect(DSN) as conn, conn.cursor() as cur:
            cur.execute("SELECT source, count(*) FROM raw_entities GROUP BY source ORDER BY source")
            await _json(send, 200, [{"source": r[0], "count": r[1]} for r in cur.fetchall()]); return
    if path == "/v1/sync" and method == "POST":
        try:
            req = urllib.request.Request(f"{WORKER}/run", method="POST", data=b"")
            urllib.request.urlopen(req, timeout=5)
            await _json(send, 202, {"sync": "kicked"}); return
        except urllib.error.URLError as e:
            await _json(send, 502, {"error": f"worker unreachable: {e}"}); return
    await _json(send, 404, {"error": "not found"})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info")
