#!/usr/bin/env python3
"""
Mock API server for sloane.
Serves mock data to enable frontend development without PostgreSQL or Go compiler.
"""
import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import sys

# Mock data
MOCK_CONTENTS = {
    "anime": [
        {"id": 1, "title": "Attack on Titan", "content_type": "anime", "cover_url": "https://picsum.photos/seed/aot/400/600", "description": "Humanity fights for survival against giant humanoid Titans.", "episode_count": 87, "status": "completed", "genres": "action,drama", "year": 2013, "rating": 9.1, "scraped_at": "2026-06-14T00:00:00Z", "last_scraped_at": "2026-06-14T00:00:00Z"},
        {"id": 2, "title": "Demon Slayer", "content_type": "anime", "cover_url": "https://picsum.photos/seed/ds/400/600", "description": "A young boy becomes a demon slayer to save his sister.", "episode_count": 44, "status": "ongoing", "genres": "action,fantasy", "year": 2019, "rating": 8.7, "scraped_at": "2026-06-14T00:00:00Z", "last_scraped_at": "2026-06-14T00:00:00Z"},
    ],
    "manga": [
        {"id": 3, "title": "Berserk", "content_type": "manga", "cover_url": "https://picsum.photos/seed/berserk/400/600", "description": "A lone mercenary's journey through a dark fantasy world.", "chapter_count": 374, "status": "ongoing", "genres": "action,dark fantasy", "year": 1989, "rating": 9.4, "scraped_at": "2026-06-14T00:00:00Z", "last_scraped_at": "2026-06-14T00:00:00Z"},
    ],
    "donghua": [
        {"id": 4, "title": "Mo Dao Zu Shi", "content_type": "donghua", "cover_url": "https://picsum.photos/seed/mdzs/400/600", "description": "A cultivation master returns from the dead.", "episode_count": 35, "status": "completed", "genres": "action,fantasy", "year": 2018, "rating": 8.9, "scraped_at": "2026-06-14T00:00:00Z", "last_scraped_at": "2026-06-14T00:00:00Z"},
    ],
    "comic": [
        {"id": 5, "title": "Tower of God", "content_type": "comic", "cover_url": "https://picsum.photos/seed/tog/400/600", "description": "A boy climbs a mysterious tower to find his friend.", "chapter_count": 550, "status": "ongoing", "genres": "action,fantasy", "year": 2010, "rating": 8.5, "scraped_at": "2026-06-14T00:00:00Z", "last_scraped_at": "2026-06-14T00:00:00Z"},
    ],
    "novel": [
        {"id": 6, "title": "Mushoku Tensei", "content_type": "novel", "cover_url": "https://picsum.photos/seed/mt/400/600", "description": "A man is reincarnated in a fantasy world.", "chapter_count": 286, "status": "completed", "genres": "fantasy,isekai", "year": 2012, "rating": 8.7, "scraped_at": "2026-06-14T00:00:00Z", "last_scraped_at": "2026-06-14T00:00:00Z"},
    ],
    "movie": [
        {"id": 7, "title": "Your Name", "content_type": "movie", "cover_url": "https://picsum.photos/seed/yn/400/600", "description": "Two teenagers share a profound connection.", "episode_count": 1, "status": "completed", "genres": "romance,drama", "year": 2016, "rating": 8.4, "scraped_at": "2026-06-14T00:00:00Z", "last_scraped_at": "2026-06-14T00:00:00Z"},
    ]
}

MOCK_STREAMS = {
    1: [{"id": 1, "content_id": 1, "episode": 1, "url": "https://example.com/stream/1/ep1", "quality": "1080p"}],
    2: [{"id": 2, "content_id": 2, "episode": 1, "url": "https://example.com/stream/2/ep1", "quality": "1080p"}],
}

MOCK_PAGES = {
    3: [{"id": 1, "content_id": 3, "chapter": 1, "page_number": 1, "url": "https://example.com/pages/3/ch1/p1.jpg"}],
    5: [{"id": 2, "content_id": 5, "chapter": 1, "page_number": 1, "url": "https://example.com/pages/5/ch1/p1.jpg"}],
}

def get_all_contents(content_type=None, limit=20, page=1):
    items = []
    for ctype, contents in MOCK_CONTENTS.items():
        if content_type and ctype != content_type:
            continue
        items.extend(contents)
    total = len(items)
    offset = (page - 1) * limit
    return {
        "data": items[offset:offset + limit],
        "meta": {"page": page, "limit": limit, "total": total, "has_next": offset + limit < total},
        "error": None
    }

def get_content(content_id):
    for ctype, contents in MOCK_CONTENTS.items():
        for item in contents:
            if item["id"] == content_id:
                return {"data": item, "meta": None, "error": None}
    return {"data": None, "meta": None, "error": {"code": 404, "message": "Content not found"}}

def get_full_content(content_id):
    content_resp = get_content(content_id)
    if content_resp["error"]:
        return content_resp
    content = content_resp["data"]
    ctype = content["content_type"]
    result = content.copy()
    if ctype in ["anime", "donghua", "movie"]:
        result["streams"] = MOCK_STREAMS.get(content_id, [])
        result["downloads"] = []
        result["pages"] = []
    else:
        result["streams"] = []
        result["downloads"] = []
        result["pages"] = MOCK_PAGES.get(content_id, [])
    return {"data": result, "meta": None, "error": None}

def search_contents(query, limit=20):
    items = []
    for ctype, contents in MOCK_CONTENTS.items():
        for item in contents:
            if query.lower() in item["title"].lower():
                items.append(item)
    return {"data": items[:limit], "meta": {"query": query, "total": len(items)}, "error": None}

def get_trending(content_type=None, limit=20):
    return get_all_contents(content_type, limit, 1)

class MockAPIHandler(BaseHTTPRequestHandler):
    def send_json_response(self, status_code, data):
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

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
            self.send_json_response(200, {"status": "ok", "timestamp": "2026-06-15T00:00:00Z"})
        elif path == "/api/contents":
            content_type = query.get("type", [None])[0]
            limit = int(query.get("limit", [20])[0])
            page = int(query.get("page", [1])[0])
            self.send_json_response(200, get_all_contents(content_type, limit, page))
        elif path.startswith("/api/contents/") and path.endswith("/full"):
            try:
                content_id = int(path.split("/")[3])
                self.send_json_response(200, get_full_content(content_id))
            except (ValueError, IndexError):
                self.send_json_response(400, {"data": None, "meta": None, "error": {"code": 400, "message": "Invalid ID"}})
        elif path.startswith("/api/contents/"):
            try:
                content_id = int(path.split("/")[3])
                self.send_json_response(200, get_content(content_id))
            except (ValueError, IndexError):
                self.send_json_response(400, {"data": None, "meta": None, "error": {"code": 400, "message": "Invalid ID"}})
        elif path == "/api/search":
            q = query.get("q", [""])[0]
            limit = int(query.get("limit", [20])[0])
            self.send_json_response(200, search_contents(q, limit))
        elif path == "/api/trending":
            content_type = query.get("type", [None])[0]
            limit = int(query.get("limit", [20])[0])
            self.send_json_response(200, get_trending(content_type, limit))
        else:
            self.send_json_response(404, {"data": None, "meta": None, "error": {"code": 404, "message": "Not found"}})

    def log_message(self, format, *args):
        print(f"[{self.log_date_time_string()}] {args[0]}")

def main():
    port = 8080
    if len(sys.argv) > 1:
        port = int(sys.argv[1])
    server = HTTPServer(("0.0.0.0", port), MockAPIHandler)
    print(f"Mock API server running on http://localhost:{port}")
    print("Endpoints: /health, /api/contents, /api/contents/{id}, /api/contents/{id}/full, /api/search, /api/trending")
    print("Press Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()

if __name__ == "__main__":
    main()