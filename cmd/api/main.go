package main

import (
	"context"
	"crypto/rand"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"strconv"
	"sync"
	"time"

	"github.com/dwizzy/sloane/internal/storage"
	"github.com/go-chi/chi/v5"
	"github.com/go-chi/chi/v5/middleware"
	"github.com/go-redis/redis/v8"
)

type Server struct {
	db       *storage.PostgresDB
	cache    *redis.Client
	ttl      time.Duration
	rateLim  *RateLimiter
	queryCache *QueryCache
}

// QueryCache - simple in-memory LRU cache for database queries
type QueryCache struct {
	mu      sync.RWMutex
	items   map[string]*cacheItem
	maxSize int
}

type cacheItem struct {
	data      []byte
	expiresAt time.Time
}

func NewQueryCache(maxSize int) *QueryCache {
	qc := &QueryCache{
		items:   make(map[string]*cacheItem),
		maxSize: maxSize,
	}
	// Cleanup expired entries every 30 seconds
	go func() {
		for {
			time.Sleep(30 * time.Second)
			qc.mu.Lock()
			now := time.Now()
			for key, item := range qc.items {
				if now.After(item.expiresAt) {
					delete(qc.items, key)
				}
			}
			qc.mu.Unlock()
		}
	}()
	return qc
}

func (qc *QueryCache) Get(key string) ([]byte, bool) {
	qc.mu.RLock()
	defer qc.mu.RUnlock()

	item, exists := qc.items[key]
	if !exists || time.Now().After(item.expiresAt) {
		return nil, false
	}
	return item.data, true
}

func (qc *QueryCache) Set(key string, data []byte, ttl time.Duration) {
	qc.mu.Lock()
	defer qc.mu.Unlock()

	// Evict oldest if at capacity
	if len(qc.items) >= qc.maxSize {
		for k := range qc.items {
			delete(qc.items, k)
			break
		}
	}

	qc.items[key] = &cacheItem{
		data:      data,
		expiresAt: time.Now().Add(ttl),
	}
}

// RateLimiter - simple in-memory per-IP rate limiter
type RateLimiter struct {
	mu      sync.Mutex
	clients map[string]*clientEntry
	maxReqs int
	window  time.Duration
}

type clientEntry struct {
	count    int
	lastSeen time.Time
}

// writeError sends a JSON error response
func writeError(w http.ResponseWriter, message string, code int) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	json.NewEncoder(w).Encode(map[string]interface{}{
		"error": message,
		"code":  code,
	})
}

func NewRateLimiter(maxReqs int, window time.Duration) *RateLimiter {
	rl := &RateLimiter{
		clients: make(map[string]*clientEntry),
		maxReqs: maxReqs,
		window:  window,
	}
	// Cleanup stale entries every minute
	go func() {
		for {
			time.Sleep(time.Minute)
			rl.mu.Lock()
			now := time.Now()
			for ip, entry := range rl.clients {
				if now.Sub(entry.lastSeen) > rl.window {
					delete(rl.clients, ip)
				}
			}
			rl.mu.Unlock()
		}
	}()
	return rl
}

func (rl *RateLimiter) Allow(ip string) bool {
	rl.mu.Lock()
	defer rl.mu.Unlock()

	entry, exists := rl.clients[ip]
	now := time.Now()

	if !exists || now.Sub(entry.lastSeen) > rl.window {
		rl.clients[ip] = &clientEntry{count: 1, lastSeen: now}
		return true
	}

	entry.count++
	entry.lastSeen = now
	return entry.count <= rl.maxReqs
}

func NewServer() (*Server, error) {
	dbURL := os.Getenv("DATABASE_URL")
	if dbURL == "" {
		dbURL = "postgresql://sloane:sloane_secure_password@localhost:6432/sloane?sslmode=disable"
	}

	db, err := storage.NewPostgresDB(dbURL)
	if err != nil {
		return nil, fmt.Errorf("failed to connect to db: %w", err)
	}

	valkeyAddr := os.Getenv("VALKEY_ADDR")
	if valkeyAddr == "" {
		valkeyAddr = "localhost:6379"
	}

	cache := redis.NewClient(&redis.Options{
		Addr:     valkeyAddr,
		Password: "",
		DB:       0,
	})

	ttl := 300 * time.Second
	if t := os.Getenv("CACHE_TTL"); t != "" {
		if secs, err := strconv.Atoi(t); err == nil {
			ttl = time.Duration(secs) * time.Second
		}
	}

	return &Server{
		db:         db,
		cache:      cache,
		ttl:        ttl,
		rateLim:    NewRateLimiter(100, time.Minute),
		queryCache: NewQueryCache(1000), // 1000 item capacity
	}, nil
}

func (s *Server) cacheGet(ctx context.Context, key string, dest interface{}) bool {
	val, err := s.cache.Get(ctx, key).Result()
	if err == redis.Nil {
		return false
	}
	if err != nil {
		return false
	}
	if err := json.Unmarshal([]byte(val), dest); err != nil {
		return false
	}
	return true
}

func (s *Server) cacheSet(ctx context.Context, key string, value interface{}) {
	data, err := json.Marshal(value)
	if err != nil {
		return
	}
	s.cache.Set(ctx, key, data, s.ttl)
}

// cachedHandler wraps a DB query with two-tier cache logic (memory + Redis)
func (s *Server) cachedHandler(cacheKey string, queryFn func(ctx context.Context) (interface{}, error)) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		ctx := r.Context()

		// Tier 1: Check in-memory cache first
		if data, ok := s.queryCache.Get(cacheKey); ok {
			w.Header().Set("Content-Type", "application/json")
			w.Header().Set("X-Cache", "HIT-MEMORY")
			w.Write(data)
			return
		}

		// Tier 2: Check Redis cache
		var data interface{}
		if s.cacheGet(ctx, cacheKey, &data) {
			// Promote to memory cache for faster access
			if jsonData, err := json.Marshal(data); err == nil {
				s.queryCache.Set(cacheKey, jsonData, s.ttl)
			}
			w.Header().Set("Content-Type", "application/json")
			w.Header().Set("X-Cache", "HIT-REDIS")
			json.NewEncoder(w).Encode(data)
			return
		}

		// Tier 3: Query database
		result, err := queryFn(ctx)
		if err != nil {
			writeError(w, err.Error(), http.StatusInternalServerError)
			return
		}

		// Cache in both tiers
		s.cacheSet(ctx, cacheKey, result)
		if jsonData, err := json.Marshal(result); err == nil {
			s.queryCache.Set(cacheKey, jsonData, s.ttl)
		}

		w.Header().Set("Content-Type", "application/json")
		w.Header().Set("X-Cache", "MISS")
		json.NewEncoder(w).Encode(result)
	}
}

func (s *Server) handleContents() http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		ctx := r.Context()
		contentType := r.URL.Query().Get("type")
		limitStr := r.URL.Query().Get("limit")
		offsetStr := r.URL.Query().Get("offset")

		limit := 50
		if l, err := strconv.Atoi(limitStr); err == nil && l > 0 && l <= 100 {
			limit = l
		}

		offset := 0
		if o, err := strconv.Atoi(offsetStr); err == nil && o >= 0 {
			offset = o
		}

		contents, total, err := s.db.GetContents(ctx, contentType, limit, offset)
		if err != nil {
			writeError(w, err.Error(), http.StatusInternalServerError)
			return
		}

		cacheKey := fmt.Sprintf("contents:%s:%d:%d", contentType, limit, offset)
		s.cacheSet(ctx, cacheKey, map[string]interface{}{
			"total": total,
			"limit": limit,
			"offset": offset,
			"items": contents,
		})

		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]interface{}{
			"total": total,
			"limit": limit,
			"offset": offset,
			"items": contents,
		})
	}
}

func (s *Server) handleContent() http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		idStr := chi.URLParam(r, "id")
		id, err := strconv.Atoi(idStr)
		if err != nil {
			writeError(w, "invalid id", http.StatusBadRequest)
			return
		}

		handler := s.cachedHandler(fmt.Sprintf("content:%d", id), func(ctx context.Context) (interface{}, error) {
			return s.db.GetContent(ctx, id)
		})
		handler(w, r)
	}
}

func (s *Server) handleContentStreams() http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		idStr := chi.URLParam(r, "id")
		id, err := strconv.Atoi(idStr)
		if err != nil {
			writeError(w, "invalid id", http.StatusBadRequest)
			return
		}

		handler := s.cachedHandler(fmt.Sprintf("content:%d:streams", id), func(ctx context.Context) (interface{}, error) {
			return s.db.GetStreams(ctx, id)
		})
		handler(w, r)
	}
}

func (s *Server) handleContentDownloads() http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		idStr := chi.URLParam(r, "id")
		id, err := strconv.Atoi(idStr)
		if err != nil {
			writeError(w, "invalid id", http.StatusBadRequest)
			return
		}

		handler := s.cachedHandler(fmt.Sprintf("content:%d:downloads", id), func(ctx context.Context) (interface{}, error) {
			return s.db.GetDownloads(ctx, id)
		})
		handler(w, r)
	}
}

func (s *Server) handleContentPages() http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		idStr := chi.URLParam(r, "id")
		id, err := strconv.Atoi(idStr)
		if err != nil {
			writeError(w, "invalid id", http.StatusBadRequest)
			return
		}

		handler := s.cachedHandler(fmt.Sprintf("content:%d:pages", id), func(ctx context.Context) (interface{}, error) {
			return s.db.GetPages(ctx, id)
		})
		handler(w, r)
	}
}

func (s *Server) handleFullContent() http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		idStr := chi.URLParam(r, "id")
		id, err := strconv.Atoi(idStr)
		if err != nil {
			writeError(w, "invalid id", http.StatusBadRequest)
			return
		}

		handler := s.cachedHandler(fmt.Sprintf("content:%d:full", id), func(ctx context.Context) (interface{}, error) {
			return s.db.GetFullContent(ctx, id)
		})
		handler(w, r)
	}
}

func (s *Server) handleStats() http.HandlerFunc {
	return s.cachedHandler("stats", func(ctx context.Context) (interface{}, error) {
		return s.db.Stats(ctx)
	})
}

func (s *Server) handleTrending() http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		ctx := r.Context()
		contentType := r.URL.Query().Get("type")
		limitStr := r.URL.Query().Get("limit")

		limit := 20
		if l, err := strconv.Atoi(limitStr); err == nil && l > 0 && l <= 50 {
			limit = l
		}

		contents, err := s.db.GetTrending(ctx, contentType, limit)
		if err != nil {
			writeError(w, err.Error(), http.StatusInternalServerError)
			return
		}

		cacheKey := fmt.Sprintf("trending:%s:%d", contentType, limit)
		s.cacheSet(ctx, cacheKey, map[string]interface{}{
			"data": contents,
			"meta": map[string]interface{}{
				"limit": limit,
				"total": len(contents),
			},
			"error": nil,
		})

		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]interface{}{
			"data": contents,
			"meta": map[string]interface{}{
				"limit": limit,
				"total": len(contents),
			},
			"error": nil,
		})
	}
}

func (s *Server) handleSearch() http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		ctx := r.Context()
		query := r.URL.Query().Get("q")
		if query == "" {
			w.Header().Set("Content-Type", "application/json")
			json.NewEncoder(w).Encode(map[string]interface{}{
				"query": "",
				"count": 0,
				"items": []interface{}{},
			})
			return
		}

		limit := 20
		if l, err := strconv.Atoi(r.URL.Query().Get("limit")); err == nil && l > 0 && l <= 50 {
			limit = l
		}

		// Check cache first
		cacheKey := fmt.Sprintf("search:%s:%d", query, limit)
		var cached interface{}
		if s.cacheGet(ctx, cacheKey, &cached) {
			w.Header().Set("Content-Type", "application/json")
			w.Header().Set("X-Cache", "HIT")
			json.NewEncoder(w).Encode(cached)
			return
		}

		contents, err := s.db.Search(ctx, query, limit)
		if err != nil {
			writeError(w, err.Error(), http.StatusInternalServerError)
			return
		}
		if contents == nil {
			contents = []storage.Content{}
		}

		result := map[string]interface{}{
			"query":    query,
			"count":    len(contents),
			"contents": contents,
		}

		// Cache search results for 60 seconds (shorter than other endpoints due to freshness)
		data, _ := json.Marshal(result)
		s.cache.Set(ctx, cacheKey, data, 60*time.Second)

		w.Header().Set("Content-Type", "application/json")
		w.Header().Set("X-Cache", "MISS")
		json.NewEncoder(w).Encode(result)
	}
}

func (s *Server) handleHealth(w http.ResponseWriter, r *http.Request) {
	ctx := r.Context()

	health := map[string]interface{}{
		"status": "healthy",
		"timestamp": time.Now().Format(time.RFC3339),
		"version": "1.0.0",
		"dependencies": map[string]interface{}{
			"database": map[string]interface{}{
				"status": "unknown",
				"error": "",
			},
			"cache": map[string]interface{}{
				"status": "unknown",
				"error": "",
			},
		},
	}

	// Check database connection with timeout
	dbCtx, dbCancel := context.WithTimeout(ctx, 2*time.Second)
	defer dbCancel()

	stats, err := s.db.Stats(dbCtx)
	if err != nil {
		health["status"] = "degraded"
		health["dependencies"].(map[string]interface{})["database"] = map[string]interface{}{
			"status": "unhealthy",
			"error": err.Error(),
		}
	} else {
		health["dependencies"].(map[string]interface{})["database"] = map[string]interface{}{
			"status": "healthy",
			"stats": stats,
		}
	}

	// Check cache connection with timeout
	cacheCtx, cacheCancel := context.WithTimeout(ctx, 2*time.Second)
	defer cacheCancel()

	err = s.cache.Ping(cacheCtx).Err()
	if err != nil {
		health["status"] = "degraded"
		health["dependencies"].(map[string]interface{})["cache"] = map[string]interface{}{
			"status": "unhealthy",
			"error": err.Error(),
		}
	} else {
		health["dependencies"].(map[string]interface{})["cache"] = map[string]interface{}{
			"status": "healthy",
		}
	}

	// Determine HTTP status code based on health
	statusCode := http.StatusOK
	if health["status"] == "degraded" {
		statusCode = http.StatusServiceUnavailable
	}

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(statusCode)
	json.NewEncoder(w).Encode(health)
}

func main() {
	server, err := NewServer()
	if err != nil {
		log.Fatalf("Failed to create server: %v", err)
	}

	r := chi.NewRouter()
	r.Use(middleware.Logger)
	r.Use(middleware.Recoverer)
	r.Use(middleware.Timeout(60 * time.Second))

	// Request ID tracking
	r.Use(func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			requestID := r.Header.Get("X-Request-ID")
			if requestID == "" {
				bytes := make([]byte, 8)
				rand.Read(bytes)
				requestID = fmt.Sprintf("req_%x", bytes)
			}
			w.Header().Set("X-Request-ID", requestID)
			next.ServeHTTP(w, r)
		})
	})

	// Rate limiting: 100 req/min per IP
	r.Use(func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			ip := r.RemoteAddr
			if forwarded := r.Header.Get("X-Forwarded-For"); forwarded != "" {
				ip = forwarded
			}
			if !server.rateLim.Allow(ip) {
				writeError(w, "Too Many Requests", http.StatusTooManyRequests)
				return
			}
			next.ServeHTTP(w, r)
		})
	})

	// Security & CSP headers for Jawatch
	r.Use(func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			w.Header().Set("Access-Control-Allow-Origin", "*")
			w.Header().Set("Access-Control-Allow-Methods", "GET, OPTIONS")
			w.Header().Set("Access-Control-Allow-Headers", "Content-Type, Accept")
			w.Header().Set("X-Content-Type-Options", "nosniff")
			w.Header().Set("X-Frame-Options", "DENY")
			w.Header().Set("X-XSS-Protection", "1; mode=block")
			w.Header().Set("Content-Security-Policy", "default-src 'self'; img-src 'self' data: https: http:; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline';")

			if r.Method == "OPTIONS" {
				w.WriteHeader(http.StatusOK)
				return
			}
			next.ServeHTTP(w, r)
		})
	})

	// Performance monitoring middleware
	r.Use(func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			start := time.Now()
			ww := middleware.NewWrapResponseWriter(w, r.ProtoMajor)
			next.ServeHTTP(ww, r)
			duration := time.Since(start)

			// Log slow requests (>500ms)
			if duration > 500*time.Millisecond {
				log.Printf("SLOW: %s %s took %v (status: %d, bytes: %d)",
					r.Method, r.URL.Path, duration, ww.Status(), ww.BytesWritten())
			}

			// Add timing header
			w.Header().Set("X-Request-Duration", duration.String())
		})
	})

	r.Get("/health", server.handleHealth)
	r.Get("/api/search", server.handleSearch())
	r.Get("/api/contents", server.handleContents())
	r.Get("/api/contents/{id}", server.handleContent())
	r.Get("/api/contents/{id}/full", server.handleFullContent())
	r.Get("/api/contents/{id}/streams", server.handleContentStreams())
	r.Get("/api/contents/{id}/downloads", server.handleContentDownloads())
	r.Get("/api/contents/{id}/pages", server.handleContentPages())
	r.Get("/api/trending", server.handleTrending())
	r.Get("/api/stats", server.handleStats())

	log.Println("Starting API server on :8080")
	if err := http.ListenAndServe(":8080", r); err != nil {
		log.Fatalf("Server failed: %v", err)
	}
}
