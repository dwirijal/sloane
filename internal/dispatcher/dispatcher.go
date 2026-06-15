package dispatcher

import (
	"context"
	"fmt"
	"log"
	"strings"
	"sync"
	"time"

	"github.com/dwizzy/sloane/internal/config"
	"github.com/dwizzy/sloane/internal/scraper"
	"github.com/dwizzy/sloane/internal/storage"
)

// Dispatcher coordinates scraping jobs across worker goroutines
type Dispatcher struct {
	cfg     *config.Config
	db      *storage.PostgresDB
	workers int
	queue   chan string // site URLs to scrape
}

// New creates a new Dispatcher
func New(cfg *config.Config, db *storage.PostgresDB) *Dispatcher {
	return &Dispatcher{
		cfg:     cfg,
		db:      db,
		workers: cfg.Concurrency,
		queue:   make(chan string, len(cfg.ScrapeSites)),
	}
}

// Run starts the scraping dispatcher
func (d *Dispatcher) Run(ctx context.Context) error {
	// Enqueue all sites
	for _, site := range d.cfg.ScrapeSites {
		d.queue <- site
	}
	close(d.queue)

	// Start workers
	var wg sync.WaitGroup
	errCh := make(chan error, d.workers)

	for i := 0; i < d.workers; i++ {
		wg.Add(1)
		go d.worker(ctx, i, &wg, errCh)
	}

	// Wait for workers to finish
	go func() {
		wg.Wait()
		close(errCh)
	}()

	// Collect errors
	var errs []error
	for err := range errCh {
		if err != nil {
			errs = append(errs, err)
		}
	}

	if len(errs) > 0 {
		log.Printf("Dispatcher finished with %d errors", len(errs))
		return fmt.Errorf("dispatcher errors: %v", errs)
	}

	// Print final stats
	stats, err := d.db.Stats(ctx)
	if err != nil {
		return fmt.Errorf("failed to get stats: %w", err)
	}
	log.Println("=" + strings.Repeat("=", 50))
	log.Println("Scraping complete!")
	log.Printf("  sources:   %d", stats["sources"])
	log.Printf("  contents:  %d", stats["contents"])
	log.Printf("  streams:   %d", stats["streams"])
	log.Printf("  downloads: %d", stats["downloads"])
	log.Printf("  pages:     %d", stats["pages"])
	log.Printf("  images:    %d", stats["images"])
	log.Println("=" + strings.Repeat("=", 50))

	return nil
}

func (d *Dispatcher) worker(ctx context.Context, id int, wg *sync.WaitGroup, errCh chan<- error) {
	defer wg.Done()

	for siteURL := range d.queue {
		select {
		case <-ctx.Done():
			return
		default:
		}

		log.Printf("[worker %d] Scraping %s", id, siteURL)

		s, err := scraper.ScrapeSite(ctx, siteURL, d.db)
		if err != nil {
			log.Printf("[worker %d] ERROR: %s - %v", id, siteURL, err)
			errCh <- fmt.Errorf("failed to scrape %s: %w", siteURL, err)
			continue
		}

		log.Printf("[worker %d] ✓ %s: %d scraped", id, siteURL, s.Scraped)

		// Rate limit between sites
		select {
		case <-ctx.Done():
			return
		case <-time.After(2 * time.Second):
		}
	}
}