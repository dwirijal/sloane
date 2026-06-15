# Sloane Scraper Machine

A high-performance, concurrent scraping system built in Go and Python, designed to extract anime and manga content from multiple sources with robust deduplication and High Availability (HA) fallback URL storage.

## Architecture

- **PostgreSQL**: Central data store with strict deduplication constraints.
- **Python Scraper**: Async engine using `httpx` + `BeautifulSoup` for deep site-specific extraction.
- **Go Dispatcher**: Concurrent worker pool for fast, coordinated scraping jobs.

## Features

- **Deduplication**: `UNIQUE` constraints on `(title, source_id)` and `(content_id, url)` prevent duplicate storage.
- **HA Fallback**: Multiple stream, download, page, and image URLs are stored per content item.
- **Concurrency**: Go worker pools and Python async/await for maximum throughput.
- **Resilience**: Retry logic with exponential backoff and rate limiting to avoid bans.

## Target Sites

1. https://v2.samehadaku.how/
2. https://anichin.cafe/
3. https://komiku.org/
4. https://keikomik.web.id/
5. https://oploverz.fans/
6. https://mangaplus.shueisha.co.jp
7. http://168.144.97.24/
8. https://139.59.196.140/

## Quick Start

```bash
# 1. Start the database
docker compose up -d postgres

# 2. Run the Python scraper
docker compose run scraper

# 3. Or run the Go dispatcher
docker compose run dispatcher
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection string | `postgresql://sloane:sloane_secure_password@localhost:5432/sloane` |
| `CONCURRENCY` | Number of concurrent workers | `5` |
| `MAX_RETRIES` | HTTP request retry attempts | `3` |
| `TIMEOUT_SECS` | Request timeout in seconds | `30` |
| `SCRAPE_SITES` | Comma-separated list of target URLs | (See config) |

## Database Schema

- `sources`: Unique site URLs
- `contents`: Core metadata (title, description, cover) — deduplicated by title+source
- `streams`: Video streaming URLs (HA fallback)
- `downloads`: Download links (HA fallback)
- `pages`: Manga page images (HA fallback)
- `images`: Cover/banner images (HA fallback)

## Security & Efficiency

- **Rate Limiting**: 500ms delay between page requests, 2s between sites.
- **Connection Pooling**: Configured max open/idle connections in Go.
- **User-Agent Rotation**: Standardized headers to mimic legitimate browsers.
- **Graceful Shutdown**: Signal handling in Go ensures clean exits.

## Development

```bash
# Python
python3 -m venv venv
source venv/bin/activate
pip install -r scraper/requirements.txt

# Go
go mod tidy
go run cmd/dispatcher/main.go
```
