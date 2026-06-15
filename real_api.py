#!/usr/bin/env python3
"""
Real API server for sloane, serving data directly from PostgreSQL.
Replaces mock_api.py to provide real scraped data to the frontend.
"""
import json
import psycopg2
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import date, datetime
from decimal import Decimal
import sys
import os

class JSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)

def json_dumps(data):
    return json.dumps(data, cls=JSONEncoder)

DB_URL = os.getenv("DATABASE_URL", "postgresql://sloane:sloane_secure_password@localhost:5432/sloane")

def get_db_connection():
    return psycopg2.connect(DB_URL)

class RealAPIHandler(BaseHTTPRequestHandler):
    def send_json_response(self, status_code, data):
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json_dumps(data).encode())

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path == "/health":
            try:
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("SELECT 1")
                cur.close()
                conn.close()
                self.send_json_response(200, {"status": "ok", "timestamp": "2026-06-15T00:00:00Z"})
            except Exception as e:
                self.send_json_response(500, {"data": None, "meta": None, "error": {"code": 500, "message": str(e)}})

        elif path == "/api/contents":
            content_type = query.get("type", [None])[0]
            page = int(query.get("page", [1])[0])
            limit = int(query.get("limit", [20])[0])
            offset = (page - 1) * limit

            try:
                conn = get_db_connection()
                cur = conn.cursor()
                if content_type:
                    cur.execute("SELECT COUNT(*) FROM contents WHERE content_type = %s", (content_type,))
                    total = cur.fetchone()[0]
                    cur.execute("""
                        SELECT id, title, source_id, content_type, description, cover_url,
                               episode_count, chapter_count, status, genres, year, rating,
                               scraped_at, last_scraped_at
                        FROM contents WHERE content_type = %s ORDER BY last_scraped_at DESC LIMIT %s OFFSET %s
                    """, (content_type, limit, offset))
                else:
                    cur.execute("SELECT COUNT(*) FROM contents")
                    total = cur.fetchone()[0]
                    cur.execute("""
                        SELECT id, title, source_id, content_type, description, cover_url,
                               episode_count, chapter_count, status, genres, year, rating,
                               scraped_at, last_scraped_at
                        FROM contents ORDER BY last_scraped_at DESC LIMIT %s OFFSET %s
                    """, (limit, offset))

                rows = cur.fetchall()
                columns = [desc[0] for desc in cur.description]
                data = [dict(zip(columns, row)) for row in rows]
                cur.close()
                conn.close()

                self.send_json_response(200, {
                    "data": data,
                    "meta": {"page": page, "limit": limit, "total": total, "has_next": offset + limit < total},
                    "error": None
                })
            except Exception as e:
                self.send_json_response(500, {"data": None, "meta": None, "error": {"code": 500, "message": str(e)}})

        elif path.startswith("/api/contents/") and path.endswith("/full"):
            try:
                content_id = int(path.split("/")[3])
                conn = get_db_connection()
                cur = conn.cursor()

                cur.execute("""
                    SELECT id, title, source_id, content_type, description, cover_url,
                           episode_count, chapter_count, status, genres, year, rating,
                           scraped_at, last_scraped_at
                    FROM contents WHERE id = %s
                """, (content_id,))
                row = cur.fetchone()
                if not row:
                    self.send_json_response(404, {"data": None, "meta": None, "error": {"code": 404, "message": "Content not found"}})
                    return

                columns = [desc[0] for desc in cur.description]
                content = dict(zip(columns, row))

                cur.execute("SELECT id, content_id, episode, url, quality, created_at FROM streams WHERE content_id = %s", (content_id,))
                content["streams"] = [dict(zip([desc[0] for desc in cur.description], r)) for r in cur.fetchall()]

                cur.execute("SELECT id, content_id, episode, url, label, created_at FROM downloads WHERE content_id = %s", (content_id,))
                content["downloads"] = [dict(zip([desc[0] for desc in cur.description], r)) for r in cur.fetchall()]

                cur.execute("SELECT id, content_id, chapter, page_number, url, created_at FROM pages WHERE content_id = %s", (content_id,))
                content["pages"] = [dict(zip([desc[0] for desc in cur.description], r)) for r in cur.fetchall()]

                cur.close()
                conn.close()
                self.send_json_response(200, {"data": content, "meta": None, "error": None})
            except Exception as e:
                self.send_json_response(500, {"data": None, "meta": None, "error": {"code": 500, "message": str(e)}})

        elif path.startswith("/api/contents/"):
            try:
                content_id = int(path.split("/")[3])
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("""
                    SELECT id, title, source_id, content_type, description, cover_url,
                           episode_count, chapter_count, status, genres, year, rating,
                           scraped_at, last_scraped_at
                    FROM contents WHERE id = %s
                """, (content_id,))
                row = cur.fetchone()
                cur.close()
                conn.close()

                if not row:
                    self.send_json_response(404, {"data": None, "meta": None, "error": {"code": 404, "message": "Content not found"}})
                    return

                columns = [desc[0] for desc in cur.description]
                self.send_json_response(200, {"data": dict(zip(columns, row)), "meta": None, "error": None})
            except Exception as e:
                self.send_json_response(500, {"data": None, "meta": None, "error": {"code": 500, "message": str(e)}})

        elif path == "/api/search":
            q = query.get("q", [""])[0]
            limit = int(query.get("limit", [20])[0])
            try:
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("""
                    SELECT id, title, source_id, content_type, description, cover_url,
                           episode_count, chapter_count, status, genres, year, rating,
                           scraped_at, last_scraped_at
                    FROM contents WHERE title ILIKE %s ORDER BY last_scraped_at DESC LIMIT %s
                """, (f"%{q}%", limit))
                rows = cur.fetchall()
                columns = [desc[0] for desc in cur.description]
                data = [dict(zip(columns, row)) for row in rows]
                cur.close()
                conn.close()
                self.send_json_response(200, {"data": data, "meta": {"query": q, "total": len(data)}, "error": None})
            except Exception as e:
                self.send_json_response(500, {"data": None, "meta": None, "error": {"code": 500, "message": str(e)}})

        elif path == "/api/trending":
            content_type = query.get("type", [None])[0]
            limit = int(query.get("limit", [20])[0])
            try:
                conn = get_db_connection()
                cur = conn.cursor()
                if content_type:
                    cur.execute("""
                        SELECT id, title, source_id, content_type, description, cover_url,
                               episode_count, chapter_count, status, genres, year, rating,
                               scraped_at, last_scraped_at
                        FROM contents WHERE content_type = %s ORDER BY last_scraped_at DESC LIMIT %s
                    """, (content_type, limit))
                else:
                    cur.execute("""
                        SELECT id, title, source_id, content_type, description, cover_url,
                               episode_count, chapter_count, status, genres, year, rating,
                               scraped_at, last_scraped_at
                        FROM contents ORDER BY last_scraped_at DESC LIMIT %s
                    """, (limit,))
                rows = cur.fetchall()
                columns = [desc[0] for desc in cur.description]
                data = [dict(zip(columns, row)) for row in rows]
                cur.close()
                conn.close()
                self.send_json_response(200, {"data": data, "meta": {"limit": limit, "total": len(data)}, "error": None})
            except Exception as e:
                self.send_json_response(500, {"data": None, "meta": None, "error": {"code": 500, "message": str(e)}})

        else:
            self.send_json_response(404, {"data": None, "meta": None, "error": {"code": 404, "message": "Not found"}})

    def log_message(self, format, *args):
        print(f"[{self.log_date_time_string()}] {args[0]}")

def main():
    port = 8080
    if len(sys.argv) > 1:
        port = int(sys.argv[1])
    server = HTTPServer(("0.0.0.0", port), RealAPIHandler)
    print(f"Real API server running on http://localhost:{port} (connected to PostgreSQL)")
    print("Endpoints: /health, /api/contents, /api/contents/{id}, /api/contents/{id}/full, /api/search, /api/trending")
    print("Press Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()

if __name__ == "__main__":
    main()