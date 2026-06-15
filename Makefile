.PHONY: help up down build test backfill cron db-shell api-shell valkey-shell

help:
	@echo "Sloane Scraper Machine"
	@echo ""
	@echo "Usage:"
	@echo "  make up           Start base services (postgres, pgbouncer, valkey, api)"
	@echo "  make down         Stop all services"
	@echo "  make backfill     Run one-time backfill"
	@echo "  make cron         Start auto-update cron (every 6 hours)"
	@echo "  make test         Run system test suite"
	@echo "  make build        Build Go binaries"
	@echo "  make db-shell     Open psql shell"
	@echo "  make api-shell    Open API container shell"
	@echo "  make valkey-shell Open Valkey CLI"

# Start base services
up:
	docker compose up -d postgres pgbouncer valkey api
	@echo "Waiting for services to be healthy..."
	@until docker compose exec postgres pg_isready -U sloane >/dev/null 2>&1; do sleep 1; done
	@echo "Base services are ready!"

# Stop all services
down:
	docker compose --profile full --profile backfill --profile cron down

# Run one-time backfill
backfill:
	docker compose --profile backfill run --rm backfill

# Start auto-update cron (runs every 6 hours)
cron:
	docker compose --profile cron up -d cron

# Run system test suite
test:
	bash test_system.sh

# PostgreSQL shell
db-shell:
	docker compose exec postgres psql -U sloane -d sloane

# API container shell
api-shell:
	docker compose exec api sh

# Valkey CLI
valkey-shell:
	docker compose exec valkey valkey-cli

# Build Go binaries
build:
	@mkdir -p bin
	go build -o bin/api ./cmd/api
	go build -o bin/dispatcher ./cmd/dispatcher

# Clean build artifacts
clean:
	rm -rf bin/
	go clean