package main

import (
	"context"
	"log"
	"os"
	"os/signal"
	"syscall"

	"github.com/dwizzy/sloane/internal/config"
	"github.com/dwizzy/sloane/internal/dispatcher"
	"github.com/dwizzy/sloane/internal/storage"
)

func main() {
	// Load configuration
	cfg, err := config.Load()
	if err != nil {
		log.Fatalf("Failed to load config: %v", err)
	}

	// Initialize storage
	db, err := storage.NewPostgresDB(cfg.DatabaseURL)
	if err != nil {
		log.Fatalf("Failed to connect to database: %v", err)
	}
	defer db.Close()

	// Create dispatcher
	disp := dispatcher.New(cfg, db)

	// Setup graceful shutdown
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)

	go func() {
		<-sigChan
		log.Println("Received shutdown signal")
		cancel()
	}()

	// Run dispatcher
	log.Println("Starting Sloane dispatcher...")
	if err := disp.Run(ctx); err != nil {
		log.Fatalf("Dispatcher error: %v", err)
	}
}
