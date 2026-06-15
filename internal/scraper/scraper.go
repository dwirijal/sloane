package scraper

import (
	"context"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/url"
	"regexp"
	"strings"
	"time"

	"github.com/dwizzy/sloane/internal/storage"
	"golang.org/x/net/html"
)

// Pre-compiled regex patterns for media URL detection (avoid per-node recompilation)
var (
	streamRe    = regexp.MustCompile(`(?i)(stream|watch|video|iframe|player|embed|mp4|m3u8)`)
	downloadRe  = regexp.MustCompile(`(?i)(download|dl\.|mp4|mkv|zip|rar)`)
	ignoreImgRe = regexp.MustCompile(`(?i)(icon|avatar|logo|ad|banner|emoji|spinner|loading)`)
)

// User agent rotation to prevent fingerprinting
var userAgents = []string{
	"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
	"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
	"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
	"Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
	"Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:121.0) Gecko/20100101 Firefox/121.0",
}

func getRandomUserAgent() string {
	return userAgents[int(time.Now().UnixNano()%int64(len(userAgents)))]
}

// Result holds scraping stats
type Result struct {
	URL     string
	Scraped int
	Failed  int
	Errors  []string
}

// ScrapeSite scrapes a single site
func ScrapeSite(ctx context.Context, siteURL string, db *storage.PostgresDB) (*Result, error) {
	log.Printf("Scraping %s", siteURL)

	// Ensure valid URL
	u, err := url.Parse(siteURL)
	if err != nil {
		return nil, fmt.Errorf("invalid URL: %w", err)
	}

	// Fetch homepage
	htmlContent, err := fetchWithRetry(ctx, siteURL, 3)
	if err != nil {
		return nil, fmt.Errorf("failed to fetch %s: %w", siteURL, err)
	}

	// Parse HTML
	doc, err := html.Parse(strings.NewReader(htmlContent))
	if err != nil {
		return nil, fmt.Errorf("failed to parse HTML: %w", err)
	}

	result := &Result{URL: siteURL}

	// Extract title
	title := extractTitle(doc)
	if title == "" {
		title = "Unknown Title"
	}

	// Extract metadata
	description := extractMetaDescription(doc)
	coverURL := extractFirstImage(doc, u)

	// Validate cover URL before storing
	if coverURL != "" {
		if !validateURL(coverURL) {
			log.Printf("Invalid cover URL for %s: %s", siteURL, coverURL)
			coverURL = ""
		}
	}

	// Determine content type from URL
	contentType := determineContentType(siteURL)

	// Upsert content
	sourceID, err := db.GetOrCreateSource(ctx, siteURL)
	if err != nil {
		return nil, err
	}

	contentID, err := db.UpsertContent(ctx, title, sourceID, contentType, description, coverURL)
	if err != nil {
		return nil, err
	}

	// Store homepage cover if found
	if coverURL != "" {
		_ = db.InsertImage(ctx, contentID, coverURL, "cover")
	}

	// Extract links
	links := extractLinks(doc, u)
	log.Printf("Found %d links on %s", len(links), siteURL)

	// Limit to first 20 links for demo
	maxLinks := 20
	if len(links) < maxLinks {
		maxLinks = len(links)
	}

	for _, link := range links[:maxLinks] {
		// Scrape each linked page
		linkHTML, err := fetchWithRetry(ctx, link, 2)
		if err != nil {
			result.Failed++
			result.Errors = append(result.Errors, link)
			continue
		}

		linkDoc, err := html.Parse(strings.NewReader(linkHTML))
		if err != nil {
			result.Failed++
			continue
		}

		linkTitle := extractTitle(linkDoc)
		if linkTitle == "" {
			continue
		}

		linkDesc := extractMetaDescription(linkDoc)
		linkCover := extractFirstImage(linkDoc, u)

		linkContentID, err := db.UpsertContent(ctx, linkTitle, sourceID, contentType, linkDesc, linkCover)
		if err != nil {
			result.Failed++
			continue
		}

		// Extract streams/downloads/pages from linked page
		extractMediaURLs(ctx, db, linkContentID, linkDoc, u)

		if linkCover != "" {
			_ = db.InsertImage(ctx, linkContentID, linkCover, "cover")
		}

		result.Scraped++

		// Rate limit
		time.Sleep(500 * time.Millisecond)
	}

	return result, nil
}

func fetchWithRetry(ctx context.Context, urlStr string, retries int) (string, error) {
	client := &http.Client{Timeout: 30 * time.Second}

	var lastErr error

	for i := 0; i < retries; i++ {
		req, err := http.NewRequestWithContext(ctx, "GET", urlStr, nil)
		if err != nil {
			return "", fmt.Errorf("creating request: %w", err)
		}

		// Rotate User-Agent per retry
		req.Header.Set("User-Agent", getRandomUserAgent())
		req.Header.Set("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8")

		resp, err := client.Do(req)
		if err != nil {
			// Network error: retry with exponential backoff
			lastErr = fmt.Errorf("request failed: %w", err)
			if i < retries-1 {
				select {
				case <-ctx.Done():
					return "", ctx.Err()
				case <-time.After(backoffDuration(i)):
				}
				continue
			}
			return "", lastErr
		}

		// Read body and close immediately (no defer in loop)
		bodyBytes, err := io.ReadAll(resp.Body)
		resp.Body.Close()

		if err != nil {
			lastErr = fmt.Errorf("reading body: %w", err)
			if i < retries-1 {
				select {
				case <-ctx.Done():
					return "", ctx.Err()
				case <-time.After(backoffDuration(i)):
				}
				continue
			}
			return "", lastErr
		}

		// Success case
		if resp.StatusCode == http.StatusOK {
			return string(bodyBytes), nil
		}

		lastErr = fmt.Errorf("HTTP %d", resp.StatusCode)

		// 4xx client errors: don't retry except for 429 (Too Many Requests)
		if resp.StatusCode >= 400 && resp.StatusCode < 500 {
			if resp.StatusCode == http.StatusTooManyRequests {
				// 429: respect Retry-After header or use exponential backoff
				waitTime := backoffDuration(i + 2) // longer wait for rate limits
				if i < retries-1 {
					log.Printf("Rate limited on %s, retrying...", urlStr)
					select {
					case <-ctx.Done():
						return "", ctx.Err()
					case <-time.After(waitTime):
					}
					continue
				}
				return "", fmt.Errorf("HTTP 429 exceeded retries: %w", lastErr)
			}
			// Other 4xx: don't retry
			return "", lastErr
		}

		// 5xx server errors: retry with exponential backoff
		if i < retries-1 {
			log.Printf("Server error %d for %s, retrying...", resp.StatusCode, urlStr)
			select {
			case <-ctx.Done():
				return "", ctx.Err()
			case <-time.After(backoffDuration(i)):
			}
			continue
		}
		return "", lastErr
	}

	return "", fmt.Errorf("max retries (%d) exceeded: %w", retries, lastErr)
}

// backoffDuration computes exponential backoff: 1s, 2s, 4s, 8s (capped at 30s)
func backoffDuration(attempt int) time.Duration {
	const maxBackoff = 30 * time.Second
	delay := time.Duration(1<<attempt) * time.Second
	if delay > maxBackoff {
		delay = maxBackoff
	}
	return delay
}

func extractTitle(n *html.Node) string {
	var title string
	var f func(*html.Node)
	f = func(n *html.Node) {
		if n.Type == html.ElementNode {
			if n.Data == "title" {
				if n.FirstChild != nil {
					title = n.FirstChild.Data
					return
				}
			}
			if n.Data == "h1" {
				if n.FirstChild != nil {
					title = n.FirstChild.Data
					return
				}
			}
		}
		for c := n.FirstChild; c != nil; c = c.NextSibling {
			f(c)
			if title != "" {
				return
			}
		}
	}
	f(n)
	return strings.TrimSpace(title)
}

func extractMetaDescription(n *html.Node) string {
	var desc string
	var f func(*html.Node)
	f = func(n *html.Node) {
		if n.Type == html.ElementNode && n.Data == "meta" {
			var name, content string
			for _, attr := range n.Attr {
				if attr.Key == "name" && attr.Val == "description" {
					name = "description"
				}
				if attr.Key == "content" {
					content = attr.Val
				}
			}
			if name == "description" && content != "" {
				desc = content
				return
			}
		}
		// Fallback: use first <p> tag as description
		if n.Type == html.ElementNode && n.Data == "p" && desc == "" {
			if n.FirstChild != nil && n.FirstChild.Data != "" {
				desc = strings.TrimSpace(n.FirstChild.Data)
				if len(desc) > 10 && desc != "" {
					return
				}
				desc = "" // Reset if too short
			}
		}
		for c := n.FirstChild; c != nil; c = c.NextSibling {
			f(c)
			if desc != "" {
				return
			}
		}
	}
	f(n)
	// Ensure we never return empty — fallback to a default
	if desc == "" {
		desc = "No description available."
	}
	return desc
}

func extractFirstImage(n *html.Node, baseURL *url.URL) string {
	var imgURL string
	var f func(*html.Node)
	f = func(n *html.Node) {
		if n.Type == html.ElementNode && n.Data == "img" {
			for _, attr := range n.Attr {
				if attr.Key == "src" && attr.Val != "" {
					abs, err := baseURL.Parse(attr.Val)
					if err == nil {
						imgURL = abs.String()
						return
					}
				}
			}
		}
		for c := n.FirstChild; c != nil; c = c.NextSibling {
			f(c)
			if imgURL != "" {
				return
			}
		}
	}
	f(n)
	return imgURL
}

// validateURL checks if a URL is well-formed and accessible
func validateURL(urlStr string) bool {
	if urlStr == "" {
		return false
	}

	// Parse URL to validate format
	_, err := url.Parse(urlStr)
	if err != nil {
		return false
	}

	// Check for common invalid patterns
	if strings.HasPrefix(urlStr, "javascript:") ||
	   strings.HasPrefix(urlStr, "data:") ||
	   strings.HasPrefix(urlStr, "#") {
		return false
	}

	// Must have protocol
	if !strings.Contains(urlStr, "://") {
		return false
	}

	return true
}

func extractLinks(n *html.Node, baseURL *url.URL) []string {
	links := make(map[string]bool)
	var f func(*html.Node)
	f = func(n *html.Node) {
		if n.Type == html.ElementNode && n.Data == "a" {
			for _, attr := range n.Attr {
				if attr.Key == "href" && attr.Val != "" {
					href := strings.TrimSpace(attr.Val)
					// Skip anchors, javascript, mailto, and very short URLs
					if href == "" || href == "#" || strings.HasPrefix(href, "javascript:") || strings.HasPrefix(href, "mailto:") || len(href) < 10 {
						continue
					}

					abs, err := baseURL.Parse(href)
					if err == nil {
						// Only same-domain links, skip fragment-only URLs
						if abs.Host == baseURL.Host && abs.Path != "" && abs.Path != "/" && abs.Path != baseURL.Path {
							links[abs.String()] = true
						}
					}
				}
			}
		}
		for c := n.FirstChild; c != nil; c = c.NextSibling {
			f(c)
		}
	}
	f(n)

	result := make([]string, 0, len(links))
	for link := range links {
		result = append(result, link)
	}
	return result
}

func extractMediaURLs(ctx context.Context, db *storage.PostgresDB, contentID int, n *html.Node, baseURL *url.URL) {
	var f func(*html.Node)
	f = func(n *html.Node) {
		if n.Type == html.ElementNode {
			if n.Data == "iframe" || n.Data == "source" || n.Data == "video" {
				for _, attr := range n.Attr {
					if (attr.Key == "src") && attr.Val != "" {
						abs, err := baseURL.Parse(attr.Val)
						if err == nil {
							href := abs.String()
							if streamRe.MatchString(href) {
								_ = db.InsertStream(ctx, contentID, 1, href, "auto")
							}
						}
					}
				}
			}
			if n.Data == "a" {
				for _, attr := range n.Attr {
					if attr.Key == "href" && attr.Val != "" {
						abs, err := baseURL.Parse(attr.Val)
						if err == nil {
							href := abs.String()
							if downloadRe.MatchString(href) {
								_ = db.InsertDownload(ctx, contentID, 1, href, "auto")
							} else if streamRe.MatchString(href) {
								_ = db.InsertStream(ctx, contentID, 1, href, "auto")
							}
						}
					}
				}
			}
			if n.Data == "img" {
				for _, attr := range n.Attr {
					if (attr.Key == "src" || attr.Key == "data-src") && attr.Val != "" {
						// Filter out tiny icons, ads, or avatars using pre-compiled regex
						if len(attr.Val) > 20 && !ignoreImgRe.MatchString(attr.Val) {
							abs, err := baseURL.Parse(attr.Val)
							if err == nil {
								// Assume sequential pages for manga sites
								_ = db.InsertPage(ctx, contentID, 1, 1, abs.String())
							}
						}
					}
				}
			}
		}
		for c := n.FirstChild; c != nil; c = c.NextSibling {
			f(c)
		}
	}
	f(n)
}

func determineContentType(siteURL string) string {
	u := strings.ToLower(siteURL)
	switch {
	case strings.Contains(u, "komiku"), strings.Contains(u, "keikomik"), strings.Contains(u, "manga"):
		return "manga"
	case strings.Contains(u, "samehadaku"), strings.Contains(u, "anichin"), strings.Contains(u, "oploverz"):
		return "anime"
	default:
		return "other"
	}
}
