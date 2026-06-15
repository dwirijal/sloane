package main

import (
	"database/sql"
	"fmt"
	"log"
	"net/http"
	"os"
	"strings"
	"time"

	_ "github.com/lib/pq"
)

type Content struct {
	ID          int
	Title       string
	Description sql.NullString
	SourceURL   string
	ContentType string
	CreatedAt   time.Time
}

type AuditReport struct {
	TotalContents      int
	EmptyTitles        int
	EmptyDescriptions  int
	DuplicateTitles    int
	BrokenURLs         int
	CheckedURLs        int
	Recommendations    []string
}

func main() {
	dbURL := os.Getenv("DATABASE_URL")
	if dbURL == "" {
		dbURL = "postgres://sloane:sloane_password@localhost:5432/sloane?sslmode=disable"
	}

	db, err := sql.Open("postgres", dbURL)
	if err != nil {
		log.Fatalf("Failed to connect to database: %v", err)
	}
	defer db.Close()

	if err := db.Ping(); err != nil {
		log.Fatalf("Failed to ping database: %v", err)
	}

	report := &AuditReport{
		Recommendations: make([]string, 0),
	}

	log.Println("Starting data quality audit...")

	// Count total contents
	err = db.QueryRow("SELECT COUNT(*) FROM contents").Scan(&report.TotalContents)
	if err != nil {
		log.Fatalf("Failed to count contents: %v", err)
	}
	log.Printf("Total contents: %d", report.TotalContents)

	// Check for empty titles
	err = db.QueryRow("SELECT COUNT(*) FROM contents WHERE title IS NULL OR title = ''").Scan(&report.EmptyTitles)
	if err != nil {
		log.Printf("Failed to count empty titles: %v", err)
	}
	log.Printf("Empty titles: %d", report.EmptyTitles)

	// Check for empty descriptions
	err = db.QueryRow("SELECT COUNT(*) FROM contents WHERE description IS NULL OR description = ''").Scan(&report.EmptyDescriptions)
	if err != nil {
		log.Printf("Failed to count empty descriptions: %v", err)
	}
	log.Printf("Empty descriptions: %d", report.EmptyDescriptions)

	// Check for duplicate titles
	rows, err := db.Query(`
		SELECT title, COUNT(*) as count
		FROM contents
		WHERE title IS NOT NULL AND title != ''
		GROUP BY title
		HAVING COUNT(*) > 1
	`)
	if err != nil {
		log.Printf("Failed to check duplicate titles: %v", err)
	} else {
		defer rows.Close()
		duplicates := 0
		for rows.Next() {
			var title string
			var count int
			if err := rows.Scan(&title, &count); err == nil {
				duplicates += count - 1
			}
		}
		report.DuplicateTitles = duplicates
		log.Printf("Duplicate titles: %d", report.DuplicateTitles)
	}

	// Check URLs (sample check - first 50)
	urlRows, err := db.Query("SELECT id, source_url FROM contents WHERE source_url IS NOT NULL LIMIT 50")
	if err != nil {
		log.Printf("Failed to query URLs: %v", err)
	} else {
		defer urlRows.Close()
		client := &http.Client{Timeout: 5 * time.Second}

		for urlRows.Next() {
			var id int
			var url string
			if err := urlRows.Scan(&id, &url); err != nil {
				continue
			}

			report.CheckedURLs++
			resp, err := client.Head(url)
			if err != nil || (resp != nil && resp.StatusCode >= 400) {
				report.BrokenURLs++
				log.Printf("Broken URL (ID %d): %s", id, url)
			}
			if resp != nil {
				resp.Body.Close()
			}
		}
		log.Printf("Checked %d URLs, found %d broken", report.CheckedURLs, report.BrokenURLs)
	}

	// Generate recommendations
	if report.EmptyTitles > 0 {
		report.Recommendations = append(report.Recommendations,
			fmt.Sprintf("Found %d empty titles - consider running cleanup or improving scraper", report.EmptyTitles))
	}
	if report.EmptyDescriptions > 0 {
		report.Recommendations = append(report.Recommendations,
			fmt.Sprintf("Found %d empty descriptions - enhance metadata extraction", report.EmptyDescriptions))
	}
	if report.DuplicateTitles > 0 {
		report.Recommendations = append(report.Recommendations,
			fmt.Sprintf("Found %d duplicate titles - consider deduplication or merging", report.DuplicateTitles))
	}
	if report.BrokenURLs > 0 {
		report.Recommendations = append(report.Recommendations,
			fmt.Sprintf("Found %d broken URLs out of %d checked - implement URL validation", report.BrokenURLs, report.CheckedURLs))
	}

	// Print report
	fmt.Println("\n" + strings.Repeat("=", 60))
	fmt.Println("DATA QUALITY AUDIT REPORT")
	fmt.Println(strings.Repeat("=", 60))
	fmt.Printf("Total Contents: %d\n", report.TotalContents)
	fmt.Printf("Empty Titles: %d (%.1f%%)\n", report.EmptyTitles,
		float64(report.EmptyTitles)/float64(report.TotalContents)*100)
	fmt.Printf("Empty Descriptions: %d (%.1f%%)\n", report.EmptyDescriptions,
		float64(report.EmptyDescriptions)/float64(report.TotalContents)*100)
	fmt.Printf("Duplicate Titles: %d\n", report.DuplicateTitles)
	fmt.Printf("Broken URLs: %d/%d (%.1f%%)\n", report.BrokenURLs, report.CheckedURLs,
		float64(report.BrokenURLs)/float64(report.CheckedURLs)*100)

	if len(report.Recommendations) > 0 {
		fmt.Println("\nRECOMMENDATIONS:")
		for i, rec := range report.Recommendations {
			fmt.Printf("%d. %s\n", i+1, rec)
		}
	} else {
		fmt.Println("\n✓ No major issues found - data quality is good!")
	}
	fmt.Println(strings.Repeat("=", 60))
}
