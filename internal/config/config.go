package config

import (
	"os"
	"strconv"
	"time"
)

type Config struct {
	DatabaseURL  string
	Concurrency  int
	MaxRetries   int
	TimeoutSecs  int
	ScrapeSites  []string
}

func Load() (*Config, error) {
	concurrency := 5
	if c := os.Getenv("CONCURRENCY"); c != "" {
		if val, err := strconv.Atoi(c); err == nil && val > 0 {
			concurrency = val
		}
	}

	maxRetries := 3
	if mr := os.Getenv("MAX_RETRIES"); mr != "" {
		if val, err := strconv.Atoi(mr); err == nil && val > 0 {
			maxRetries = val
		}
	}

	timeoutSecs := 30
	if t := os.Getenv("TIMEOUT_SECS"); t != "" {
		if val, err := strconv.Atoi(t); err == nil && val > 0 {
			timeoutSecs = val
		}
	}

	dbURL := os.Getenv("DATABASE_URL")
	if dbURL == "" {
		dbURL = "postgresql://sloane:sloane_secure_password@localhost:5432/sloane?sslmode=disable"
	}

	sites := []string{
		"https://v2.samehadaku.how/",
		"https://anichin.cafe/",
		"https://komiku.org/",
		"https://keikomik.web.id/",
		"https://oploverz.fans/",
		"https://mangaplus.shueisha.co.jp",
		"http://168.144.97.24/",
		"https://139.59.196.140/",
	}

	if envSites := os.Getenv("SCRAPE_SITES"); envSites != "" {
		sites = []string{}
		for _, s := range splitComma(envSites) {
			sites = append(sites, s)
		}
	}

	return &Config{
		DatabaseURL: dbURL,
		Concurrency: concurrency,
		MaxRetries:  maxRetries,
		TimeoutSecs: timeoutSecs,
		ScrapeSites: sites,
	}, nil
}

func splitComma(s string) []string {
	var result []string
	start := 0
	for i := 0; i < len(s); i++ {
		if s[i] == ',' {
			result = append(result, s[start:i])
			start = i + 1
		}
	}
	if start < len(s) {
		result = append(result, s[start:])
	}
	return result
}

func (c *Config) Timeout() time.Duration {
	return time.Duration(c.TimeoutSecs) * time.Second
}
