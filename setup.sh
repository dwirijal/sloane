#!/bin/bash
set -e

echo "=== Sloane + Jawatch Full Setup ==="
echo ""

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

info() { echo -e "${BLUE}ℹ${NC} $1"; }
success() { echo -e "${GREEN}✓${NC} $1"; }
warn() { echo -e "${YELLOW}⚠${NC} $1"; }

# Check for sudo
if [ "$EUID" -ne 0 ]; then
  warn "This script requires sudo to run Docker commands"
  warn "Please run: sudo bash setup.sh"
  exit 1
fi

cd /home/dwizzy/sloane

# Step 1: Start infrastructure
info "Starting PostgreSQL, PgBouncer, Valkey, and API..."
docker compose up -d

# Step 2: Wait for database to be healthy
info "Waiting for database to be ready..."
until docker compose exec postgres pg_isready -U sloane >/dev/null 2>&1; do
  sleep 2
done
success "Database is healthy!"

# Step 3: Check API health
info "Checking API health..."
until curl -s http://localhost:8080/health | grep -q "healthy"; do
  sleep 2
done
success "API is healthy!"

# Step 4: Run backfill
info "Running backfill (this will take a few minutes)..."
docker compose --profile backfill run --rm backfill

# Step 5: Start auto-update cron
info "Starting auto-update cron (runs every 6 hours)..."
docker compose --profile cron up -d cron
success "Cron started!"

# Step 6: Check results
echo ""
success "Backfill complete! Checking results:"
curl -s http://localhost:8080/api/stats | python3 -m json.tool

echo ""
info "Starting Jawatch frontend..."

# Step 7: Install bun if needed
if ! command -v bun &> /dev/null; then
  info "Installing bun..."
  curl -fsSL https://bun.sh/install | bash
  export PATH="$HOME/.bun/bin:$PATH"
fi

# Step 8: Setup and run Jawatch
cd /home/dwizzy/jawatch

if [ ! -d "node_modules" ]; then
  info "Installing Jawatch dependencies..."
  bun install
fi

info "Starting Jawatch development server..."
success "Jawatch will be available at http://localhost:3000"
echo ""
echo "=== Setup Complete! ==="
echo ""
echo "Sloane API: http://localhost:8080"
echo "Jawatch UI: http://localhost:3000"
echo ""
echo "To check status:"
echo "  curl http://localhost:8080/health"
echo "  curl http://localhost:8080/api/stats"
echo ""
echo "To view logs:"
echo "  docker compose logs -f"
echo ""
echo "To stop everything:"
echo "  cd /home/dwizzy/sloane && docker compose down"
echo ""

# Start Jawatch in background
bun run dev &
