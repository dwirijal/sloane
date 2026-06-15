-- Initialize Sloane database
-- Ensures deduplication by title while allowing HA fallback for stream/download/pages/images URLs

-- Sources table: track which site each content came from
CREATE TABLE IF NOT EXISTS sources (
    id          SERIAL PRIMARY KEY,
    url         TEXT UNIQUE NOT NULL,
    created_at  TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Main content table: unique by title, source pair
CREATE TABLE IF NOT EXISTS contents (
    id              SERIAL PRIMARY KEY,
    title           TEXT NOT NULL,
    source_id       INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    content_type    VARCHAR(50) NOT NULL CHECK (content_type IN ('anime', 'manga', 'movie', 'donghua', 'comic', 'novel', 'other')),
    description     TEXT,
    cover_url       TEXT,
    episode_count   INTEGER,
    chapter_count   INTEGER,
    status          VARCHAR(50),
    genres          TEXT,
    year            INTEGER,
    rating          DECIMAL(3,2),
    scraped_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    last_scraped_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE(title, source_id)
);

-- Streams for anime content (HA fallback: multiple URLs per content)
CREATE TABLE IF NOT EXISTS streams (
    id          SERIAL PRIMARY KEY,
    content_id  INTEGER NOT NULL REFERENCES contents(id) ON DELETE CASCADE,
    episode     INTEGER,
    url         TEXT NOT NULL,
    quality     VARCHAR(20),
    created_at  TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE(content_id, episode, url)
);

-- Download links
CREATE TABLE IF NOT EXISTS downloads (
    id          SERIAL PRIMARY KEY,
    content_id  INTEGER NOT NULL REFERENCES contents(id) ON DELETE CASCADE,
    episode     INTEGER,
    url         TEXT NOT NULL,
    label       VARCHAR(100),
    created_at  TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE(content_id, episode, url)
);

-- Pages for manga content
CREATE TABLE IF NOT EXISTS pages (
    id          SERIAL PRIMARY KEY,
    content_id  INTEGER NOT NULL REFERENCES contents(id) ON DELETE CASCADE,
    chapter     INTEGER,
    page_number INTEGER NOT NULL,
    url         TEXT NOT NULL,
    created_at  TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE(content_id, chapter, page_number, url)
);

-- Images (covers, banners, etc.) for HA fallback
CREATE TABLE IF NOT EXISTS images (
    id          SERIAL PRIMARY KEY,
    content_id  INTEGER NOT NULL REFERENCES contents(id) ON DELETE CASCADE,
    url         TEXT NOT NULL,
    image_type  VARCHAR(50) NOT NULL DEFAULT 'cover',
    created_at  TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE(content_id, url)
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_contents_title ON contents(title);
CREATE INDEX IF NOT EXISTS idx_contents_source ON contents(source_id);
CREATE INDEX IF NOT EXISTS idx_contents_scraped_at ON contents(scraped_at DESC);
CREATE INDEX IF NOT EXISTS idx_contents_last_scraped_at ON contents(last_scraped_at DESC);
CREATE INDEX IF NOT EXISTS idx_contents_type ON contents(content_type);
CREATE INDEX IF NOT EXISTS idx_streams_content ON streams(content_id);
CREATE INDEX IF NOT EXISTS idx_downloads_content ON downloads(content_id);
CREATE INDEX IF NOT EXISTS idx_pages_content ON pages(content_id);
CREATE INDEX IF NOT EXISTS idx_images_content ON images(content_id);
