package storage

import (
	"context"
	"database/sql"
	"fmt"
	"time"

	_ "github.com/lib/pq"
)

type PostgresDB struct {
	db *sql.DB
}

func NewPostgresDB(dsn string) (*PostgresDB, error) {
	db, err := sql.Open("postgres", dsn)
	if err != nil {
		return nil, fmt.Errorf("failed to open database: %w", err)
	}

	// Test connection
	if err := db.Ping(); err != nil {
		return nil, fmt.Errorf("failed to ping database: %w", err)
	}

	// Optimized for 2GB system with PgBouncer (transaction mode)
	db.SetMaxOpenConns(10)
	db.SetMaxIdleConns(5)
	db.SetConnMaxLifetime(5 * time.Minute)

	return &PostgresDB{db: db}, nil
}

func (p *PostgresDB) Close() {
	if p.db != nil {
		p.db.Close()
	}
}

// GetOrCreateSource gets or creates a source record, returns its ID
func (p *PostgresDB) GetOrCreateSource(ctx context.Context, url string) (int, error) {
	var id int
	err := p.db.QueryRowContext(ctx, `
		WITH ins AS (
			INSERT INTO sources (url) VALUES ($1)
			ON CONFLICT (url) DO NOTHING
			RETURNING id
		)
		SELECT id FROM ins
		UNION ALL
		SELECT id FROM sources WHERE url = $1
		LIMIT 1
	`, url).Scan(&id)

	if err != nil {
		return 0, fmt.Errorf("failed to get/create source: %w", err)
	}
	return id, nil
}

// UpsertContent inserts or updates content, returns its ID.
// Deduplication is handled by ON CONFLICT (title, source_id)
func (p *PostgresDB) UpsertContent(ctx context.Context, title string, sourceID int, contentType string, description, coverURL string, episodeCount, chapterCount *int, status, genres string, year *int, rating *float64) (int, error) {
	var id int
	err := p.db.QueryRowContext(ctx, `
		INSERT INTO contents (title, source_id, content_type, description, cover_url, episode_count, chapter_count, status, genres, year, rating)
		VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
		ON CONFLICT (title, source_id) DO UPDATE
			SET description = COALESCE(EXCLUDED.description, contents.description),
			    cover_url = COALESCE(EXCLUDED.cover_url, contents.cover_url),
			    episode_count = COALESCE(EXCLUDED.episode_count, contents.episode_count),
			    chapter_count = COALESCE(EXCLUDED.chapter_count, contents.chapter_count),
			    status = COALESCE(EXCLUDED.status, contents.status),
			    genres = COALESCE(EXCLUDED.genres, contents.genres),
			    year = COALESCE(EXCLUDED.year, contents.year),
			    rating = COALESCE(EXCLUDED.rating, contents.rating),
			    scraped_at = NOW(),
			    last_scraped_at = NOW()
		RETURNING id
	`, title, sourceID, contentType, description, coverURL, episodeCount, chapterCount, status, genres, year, rating).Scan(&id)

	if err != nil {
		return 0, fmt.Errorf("failed to upsert content: %w", err)
	}
	return id, nil
}

// InsertStream inserts a stream URL, ignoring duplicates
func (p *PostgresDB) InsertStream(ctx context.Context, contentID int, episode int, url string, quality string) error {
	_, err := p.db.ExecContext(ctx, `
		INSERT INTO streams (content_id, episode, url, quality)
		VALUES ($1, $2, $3, $4)
		ON CONFLICT (content_id, episode, url) DO NOTHING
	`, contentID, episode, url, quality)
	return err
}

// InsertDownload inserts a download URL, ignoring duplicates
func (p *PostgresDB) InsertDownload(ctx context.Context, contentID int, episode int, url string, label string) error {
	_, err := p.db.ExecContext(ctx, `
		INSERT INTO downloads (content_id, episode, url, label)
		VALUES ($1, $2, $3, $4)
		ON CONFLICT (content_id, episode, url) DO NOTHING
	`, contentID, episode, url, label)
	return err
}

// InsertPage inserts a page URL, ignoring duplicates
func (p *PostgresDB) InsertPage(ctx context.Context, contentID int, chapter int, pageNumber int, url string) error {
	_, err := p.db.ExecContext(ctx, `
		INSERT INTO pages (content_id, chapter, page_number, url)
		VALUES ($1, $2, $3, $4)
		ON CONFLICT (content_id, chapter, page_number, url) DO NOTHING
	`, contentID, chapter, pageNumber, url)
	return err
}

// InsertImage inserts an image URL, ignoring duplicates
func (p *PostgresDB) InsertImage(ctx context.Context, contentID int, url string, imageType string) error {
	_, err := p.db.ExecContext(ctx, `
		INSERT INTO images (content_id, url, image_type)
		VALUES ($1, $2, $3)
		ON CONFLICT (content_id, url) DO NOTHING
	`, contentID, url, imageType)
	return err
}

// Stats returns database statistics
func (p *PostgresDB) Stats(ctx context.Context) (map[string]int, error) {
	stats := make(map[string]int)

	rows, err := p.db.QueryContext(ctx, `
		SELECT 'sources' as tbl, count(*) FROM sources UNION ALL
		SELECT 'contents', count(*) FROM contents UNION ALL
		SELECT 'streams', count(*) FROM streams UNION ALL
		SELECT 'downloads', count(*) FROM downloads UNION ALL
		SELECT 'pages', count(*) FROM pages UNION ALL
		SELECT 'images', count(*) FROM images
	`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	for rows.Next() {
		var tbl string
		var count int
		if err := rows.Scan(&tbl, &count); err != nil {
			return nil, err
		}
		stats[tbl] = count
	}
	return stats, rows.Err()
}

// Content represents a scraped content item
type Content struct {
	ID            int       `json:"id"`
	Title         string    `json:"title"`
	SourceID      int       `json:"source_id"`
	ContentType   string    `json:"content_type"`
	Description   string    `json:"description,omitempty"`
	CoverURL      string    `json:"cover_url,omitempty"`
	EpisodeCount  *int      `json:"episode_count,omitempty"`
	ChapterCount  *int      `json:"chapter_count,omitempty"`
	Status        string    `json:"status,omitempty"`
	Genres        string    `json:"genres,omitempty"`
	Year          *int      `json:"year,omitempty"`
	Rating        *float64  `json:"rating,omitempty"`
	ScrapedAt     time.Time `json:"scraped_at"`
	LastScrapedAt time.Time `json:"last_scraped_at"`
}

// GetContents returns contents with optional type filter and pagination
func (p *PostgresDB) GetContents(ctx context.Context, contentType string, limit, offset int) ([]Content, int, error) {
	if limit <= 0 || limit > 100 {
		limit = 50
	}
	if offset < 0 {
		offset = 0
	}

	var total int
	countQuery := "SELECT count(*) FROM contents"
	if contentType != "" {
		countQuery += " WHERE content_type = $1"
		err := p.db.QueryRowContext(ctx, countQuery, contentType).Scan(&total)
		if err != nil {
			return nil, 0, fmt.Errorf("failed to count contents: %w", err)
		}
	} else {
		err := p.db.QueryRowContext(ctx, countQuery).Scan(&total)
		if err != nil {
			return nil, 0, fmt.Errorf("failed to count contents: %w", err)
		}
	}

	query := `
		SELECT id, title, source_id, content_type, description, cover_url, episode_count, chapter_count, status, genres, year, rating, scraped_at, last_scraped_at
		FROM contents`
	args := []interface{}{}
	argIdx := 1

	if contentType != "" {
		query += fmt.Sprintf(" WHERE content_type = $%d", argIdx)
		args = append(args, contentType)
		argIdx++
	}

	query += fmt.Sprintf(" ORDER BY scraped_at DESC LIMIT $%d OFFSET $%d", argIdx, argIdx+1)
	args = append(args, limit, offset)

	rows, err := p.db.QueryContext(ctx, query, args...)
	if err != nil {
		return nil, 0, fmt.Errorf("failed to query contents: %w", err)
	}
	defer rows.Close()

	var contents []Content
	for rows.Next() {
		var c Content
		if err := rows.Scan(&c.ID, &c.Title, &c.SourceID, &c.ContentType, &c.Description, &c.CoverURL, &c.EpisodeCount, &c.ChapterCount, &c.Status, &c.Genres, &c.Year, &c.Rating, &c.ScrapedAt, &c.LastScrapedAt); err != nil {
			return nil, 0, fmt.Errorf("failed to scan content: %w", err)
		}
		contents = append(contents, c)
	}
	return contents, total, rows.Err()
}

// GetContent returns a single content by ID
func (p *PostgresDB) GetContent(ctx context.Context, id int) (*Content, error) {
	var c Content
	err := p.db.QueryRowContext(ctx, `
		SELECT id, title, source_id, content_type, description, cover_url, episode_count, chapter_count, status, genres, year, rating, scraped_at, last_scraped_at
		FROM contents WHERE id = $1
	`, id).Scan(&c.ID, &c.Title, &c.SourceID, &c.ContentType, &c.Description, &c.CoverURL, &c.EpisodeCount, &c.ChapterCount, &c.Status, &c.Genres, &c.Year, &c.Rating, &c.ScrapedAt, &c.LastScrapedAt)
	if err != nil {
		return nil, err
	}
	return &c, nil
}

// Stream represents a stream URL
type Stream struct {
	ID        int       `json:"id"`
	ContentID int       `json:"content_id"`
	Episode   int       `json:"episode"`
	URL       string    `json:"url"`
	Quality   string    `json:"quality,omitempty"`
	CreatedAt time.Time `json:"created_at"`
}

// GetStreams returns all streams for a content
func (p *PostgresDB) GetStreams(ctx context.Context, contentID int) ([]Stream, error) {
	rows, err := p.db.QueryContext(ctx, `
		SELECT id, content_id, episode, url, quality, created_at
		FROM streams WHERE content_id = $1 ORDER BY episode, quality
	`, contentID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var streams []Stream
	for rows.Next() {
		var s Stream
		if err := rows.Scan(&s.ID, &s.ContentID, &s.Episode, &s.URL, &s.Quality, &s.CreatedAt); err != nil {
			return nil, err
		}
		streams = append(streams, s)
	}
	return streams, rows.Err()
}

// Download represents a download URL
type Download struct {
	ID        int       `json:"id"`
	ContentID int       `json:"content_id"`
	Episode   int       `json:"episode"`
	URL       string    `json:"url"`
	Label     string    `json:"label,omitempty"`
	CreatedAt time.Time `json:"created_at"`
}

// GetDownloads returns all downloads for a content
func (p *PostgresDB) GetDownloads(ctx context.Context, contentID int) ([]Download, error) {
	rows, err := p.db.QueryContext(ctx, `
		SELECT id, content_id, episode, url, label, created_at
		FROM downloads WHERE content_id = $1 ORDER BY episode, label
	`, contentID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var downloads []Download
	for rows.Next() {
		var d Download
		if err := rows.Scan(&d.ID, &d.ContentID, &d.Episode, &d.URL, &d.Label, &d.CreatedAt); err != nil {
			return nil, err
		}
		downloads = append(downloads, d)
	}
	return downloads, rows.Err()
}

// Page represents a manga page URL
type Page struct {
	ID         int       `json:"id"`
	ContentID  int       `json:"content_id"`
	Chapter    int       `json:"chapter"`
	PageNumber int       `json:"page_number"`
	URL        string    `json:"url"`
	CreatedAt  time.Time `json:"created_at"`
}

// GetPages returns all pages for a content
func (p *PostgresDB) GetPages(ctx context.Context, contentID int) ([]Page, error) {
	rows, err := p.db.QueryContext(ctx, `
		SELECT id, content_id, chapter, page_number, url, created_at
		FROM pages WHERE content_id = $1 ORDER BY chapter, page_number
	`, contentID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var pages []Page
	for rows.Next() {
		var pg Page
		if err := rows.Scan(&pg.ID, &pg.ContentID, &pg.Chapter, &pg.PageNumber, &pg.URL, &pg.CreatedAt); err != nil {
			return nil, err
		}
		pages = append(pages, pg)
	}
	return pages, rows.Err()
}

// FullContent represents a content item with all its media
type FullContent struct {
	Content
	Streams   []Stream   `json:"streams"`
	Downloads []Download `json:"downloads"`
	Pages     []Page     `json:"pages"`
}

// GetFullContent returns a content item with all its streams, downloads, and pages
func (p *PostgresDB) GetFullContent(ctx context.Context, contentID int) (*FullContent, error) {
	content, err := p.GetContent(ctx, contentID)
	if err != nil {
		return nil, err
	}

	streams, _ := p.GetStreams(ctx, contentID)
	downloads, _ := p.GetDownloads(ctx, contentID)
	pages, _ := p.GetPages(ctx, contentID)

	return &FullContent{
		Content:   *content,
		Streams:   streams,
		Downloads: downloads,
		Pages:     pages,
	}, nil
}

// Search searches contents by title using ILIKE (case-insensitive)
func (p *PostgresDB) Search(ctx context.Context, query string, limit int) ([]Content, error) {
	if limit <= 0 || limit > 50 {
		limit = 20
	}
	rows, err := p.db.QueryContext(ctx, `
		SELECT id, title, source_id, content_type, description, cover_url, episode_count, chapter_count, status, genres, year, rating, scraped_at, last_scraped_at
		FROM contents
		WHERE title ILIKE $1
		ORDER BY scraped_at DESC
		LIMIT $2
	`, "%"+query+"%", limit)
	if err != nil {
		return nil, fmt.Errorf("failed to search contents: %w", err)
	}
	defer rows.Close()

	var contents []Content
	for rows.Next() {
		var c Content
		if err := rows.Scan(&c.ID, &c.Title, &c.SourceID, &c.ContentType, &c.Description, &c.CoverURL, &c.EpisodeCount, &c.ChapterCount, &c.Status, &c.Genres, &c.Year, &c.Rating, &c.ScrapedAt, &c.LastScrapedAt); err != nil {
			return nil, fmt.Errorf("failed to scan content: %w", err)
		}
		contents = append(contents, c)
	}
	return contents, rows.Err()
}

// GetTrending returns most recently scraped contents, optionally filtered by type
func (p *PostgresDB) GetTrending(ctx context.Context, contentType string, limit int) ([]Content, error) {
	if limit <= 0 || limit > 50 {
		limit = 20
	}

	query := `
		SELECT id, title, source_id, content_type, description, cover_url, episode_count, chapter_count, status, genres, year, rating, scraped_at, last_scraped_at
		FROM contents`
	args := []interface{}{}
	argIdx := 1

	if contentType != "" {
		query += fmt.Sprintf(" WHERE content_type = $%d", argIdx)
		args = append(args, contentType)
		argIdx++
	}

	query += fmt.Sprintf(" ORDER BY last_scraped_at DESC LIMIT $%d", argIdx)
	args = append(args, limit)

	rows, err := p.db.QueryContext(ctx, query, args...)
	if err != nil {
		return nil, fmt.Errorf("failed to query trending: %w", err)
	}
	defer rows.Close()

	var contents []Content
	for rows.Next() {
		var c Content
		if err := rows.Scan(&c.ID, &c.Title, &c.SourceID, &c.ContentType, &c.Description, &c.CoverURL, &c.EpisodeCount, &c.ChapterCount, &c.Status, &c.Genres, &c.Year, &c.Rating, &c.ScrapedAt, &c.LastScrapedAt); err != nil {
			return nil, fmt.Errorf("failed to scan trending content: %w", err)
		}
		contents = append(contents, c)
	}
	return contents, rows.Err()
}
