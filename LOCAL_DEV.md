# Local Development Without Docker

This guide enables dwizzyOS development when Docker/PostgreSQL are unavailable.

## Prerequisites

- Python 3.12+
- Node.js 18+ (bun or npm)

## Architecture

```
[Mock API (Python)] → [jawatch (Next.js)] → [Browser]
     ↑
     └── Sloane API (mock_api.py)
```

## Step 1: Start the Mock API

```bash
cd /home/dwizzy/sloane
python3 mock_api.py
```

This starts a mock API server on `http://localhost:8080` with:
- 7 sample content items (all 6 content types)
- All standard endpoints: `/health`, `/api/contents`, `/api/contents/{id}`, `/api/contents/{id}/full`, `/api/search`, `/api/trending`
- CORS enabled for jawatch
- Response envelope: `{data, meta, error}`

## Step 2: Start Jawatch Frontend

```bash
cd /home/dwizzy/jawatch
# Option A: Using npm
npm install
npm run dev

# Option B: Using bun
bun install
bun dev
```

Open `http://localhost:3000` in your browser.

## Step 3: Verify the Integration

1. Homepage should display hero banner + content sections for all 6 types
2. Click any content card → should show detail page with mock data
3. Search should filter mock content by title
4. Loading skeletons should appear on async routes

## Available Mock Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /health` | Health check |
| `GET /api/contents?type=&page=&limit=` | List contents |
| `GET /api/contents/{id}` | Single content |
| `GET /api/contents/{id}/full` | Content with streams/pages |
| `GET /api/search?q=&limit=` | Search by title |
| `GET /api/trending?type=&limit=` | Recently scraped |

## Generating More Mock Data

```bash
cd /home/dwizzy/sloane
python3 scripts/generate_mock_data.py
# Generates: mock_contents.json, mock_streams.json, mock_pages.json
```

## Troubleshooting

### API fetch failed (ECONNREFUSED)
- Ensure mock API is running: `python3 mock_api.py`
- Check port: default is 8080, change with `python3 mock_api.py 8081`

### Build errors in jawatch
- Clear cache: `rm -rf .next node_modules`
- Reinstall: `npm install`
- Verify Node.js version: `node --version` (requires 18+)

### Missing content types
- Edit `mock_api.py` to add more sample data
- All 6 content types must have at least one item for homepage sections to render

## Limitations

- Mock data is static (no database persistence)
- Streams/pages are placeholder URLs
- No authentication (heimdall integration disabled)
- No real scraping (sloane scrapers require PostgreSQL)

## Next Steps (with Docker)

When Docker becomes available:
1. Start PostgreSQL: `docker compose up -d postgres`
2. Run migrations: `psql -h localhost -U sloane -f scripts/init.sql`
3. Run scraper: `python main.py`
4. Start real API: `go run cmd/api/main.go`
5. Update `NEXT_PUBLIC_API_URL` in jawatch `.env`