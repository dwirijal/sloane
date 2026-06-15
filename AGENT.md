# AI Agent Guidelines — Sloane

## Purpose
- **Description**: High-performance concurrent scraping system for anime, manga, movie, donghua, comic, and novel content.
- **Use Case**: Data acquisition layer for dwizzyOS — scrapes external sites, normalizes, deduplicates, and stores content in PostgreSQL, then exposes it via a REST API.
- **Core Logic**: Python async scraper (httpx + BeautifulSoup) for deep extraction, Go dispatcher for concurrent worker pool coordination, Go API server (Chi router) for serving content with two-tier caching (in-memory LRU + Redis/Valkey).

## Architecture
```
[External Sites] → Python Scraper → PostgreSQL (dedup on title+source_id)
                 → Go Dispatcher  → worker pool coordination
PostgreSQL → Go API Server (Chi) → jawatch frontend
           ↕ Valkey/Redis cache
           ↕ In-memory QueryCache (LRU)
```

## Content Types
7 types in `contents.content_type` CHECK constraint:
- `anime` — Japanese animation (Samehadaku, Oploverz)
- `manga` — Japanese comics (Komiku, MangaPlus)
- `donghua` — Chinese animation (Anichin)
- `comic` — Indonesian/other comics (Keikomik)
- `novel` — Light novels/web novels
- `movie` — Feature films
- `other` — Fallback

## DB Schema (key tables)
- `sources` — site URLs
- `contents` — title, source_id, content_type, description, cover_url, episode_count, chapter_count, status, genres, year, rating, scraped_at, last_scraped_at
- `streams` — video URLs per content (HA fallback)
- `downloads` — download links per content
- `pages` — manga page images per content
- `images` — cover/banner images per content

## API Endpoints
- `GET /health` — health check (DB + cache status)
- `GET /api/contents?type=&limit=&offset=` — list contents with pagination
- `GET /api/contents/{id}` — single content detail
- `GET /api/contents/{id}/full` — content + streams + downloads + pages
- `GET /api/contents/{id}/streams` — streams for a content
- `GET /api/contents/{id}/downloads` — downloads for a content
- `GET /api/contents/{id}/pages` — pages for a content
- `GET /api/trending?type=&limit=` — most recently scraped content
- `GET /api/search?q=&limit=` — ILIKE title search
- `GET /api/stats` — database statistics

## Target Sites
1. `https://v2.samehadaku.how/` — anime
2. `https://anichin.cafe/` — donghua
3. `https://komiku.org/` — manga
4. `https://keikomik.web.id/` — comic
5. `https://oploverz.fans/` — anime
6. `https://mangaplus.shueisha.co.jp` — manga
7. `http://168.144.97.24/` — generic
8. `https://139.59.196.140/` — generic

## Key Files
- `cmd/api/main.go` — API server (Chi router, rate limiting, caching)
- `cmd/dispatcher/main.go` — Go dispatcher
- `cmd/audit/main.go` — audit tool
- `internal/storage/storage.go` — PostgreSQL queries + models
- `internal/scraper/scraper.go` — Go scraper logic
- `internal/dispatcher/dispatcher.go` — Go worker pool
- `internal/config/config.go` — configuration
- `scraper/engine.py` — Python async scraping engine
- `scraper/sites.py` — per-site scraper classes
- `scraper/storage.py` — Python asyncpg DB operations
- `main.py` — Python CLI entry point
- `scripts/init.sql` — DB schema

## Rules
- Deduplication: `ON CONFLICT (title, source_id)` in contents, `ON CONFLICT` in streams/downloads/pages/images
- HA fallback: multiple URLs per content item stored
- Rate limiting: 500ms between page requests, 2s between sites
- User-Agent rotation: standardized headers
- Graceful shutdown: signal handling in Go
- Two-tier cache: in-memory LRU (1000 items) + Redis/Valkey (300s TTL)
- CORS enabled for jawatch consumption
- Response envelope target: `{ data, meta, error }`

## Local Commands
- Start DB: `docker compose up -d postgres pgbouncer valkey`
- Run API: `docker compose up -d api` or `go run cmd/api/main.go`
- Run scraper: `docker compose --profile full run --rm scraper` or `python main.py`
- Run dispatcher: `docker compose --profile full run --rm dispatcher` or `go run cmd/dispatcher/main.go`
- Backfill: `docker compose --profile backfill run --rm backfill` or `python backfill.py`

## Testing
Scraper tests are located in the `tests/` directory using pytest.

```bash
# Install dependencies (includes pytest and pytest-asyncio)
pip install -r scraper/requirements.txt

# Run all tests
pytest tests/ -v

# Run specific test file
pytest tests/test_sites.py -v

# Run with coverage
pytest tests/ --cov=scraper --cov-report=term-missing
```

### Test Coverage
- **test_sites.py**: Tests for scraper site registry and URL matching (8 tests)
- **test_engine.py**: Tests for scraping engine functions (2 tests)

**Note**: Requires pytest 8.3.5+ and pytest-asyncio 0.25.0+ (included in scraper/requirements.txt)

## Commit Style
- Conventional Commits: `type(scope): description`
- Types: feat, fix, refactor, docs, test, chore, perf, ci

## Security
- No hardcoded secrets — use env vars
- Validate all external inputs
- Rate limit all API endpoints (100 req/min per IP)
- Security headers: X-Content-Type-Options, X-Frame-Options, X-XSS-Protection, CSP
