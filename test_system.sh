#!/bin/bash
set -e

echo "=== Sloane System Test Suite ==="

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Test counter
TESTS_PASSED=0
TESTS_FAILED=0

# Helper function for test results
pass() {
    echo -e "${GREEN}✓${NC} $1"
    TESTS_PASSED=$((TESTS_PASSED + 1))
}

fail() {
    echo -e "${RED}✗${NC} $1"
    TESTS_FAILED=$((TESTS_FAILED + 1))
}

warn() {
    echo -e "${YELLOW}⚠${NC} $1"
}

# Test 1: Check required tools
echo ""
echo "--- Checking prerequisites ---"

if command -v docker &> /dev/null; then
    pass "Docker is installed"
else
    fail "Docker is not installed"
fi

if docker compose version &> /dev/null; then
    pass "Docker Compose is available"
else
    fail "Docker Compose is not available"
fi

if [ -f "docker-compose.yml" ]; then
    pass "docker-compose.yml exists"
else
    fail "docker-compose.yml not found"
fi

# Test 2: Check Go code compiles
echo ""
echo "--- Checking Go code ---"

export GOROOT=/home/dwizzy/go
export PATH=$GOROOT/bin:$PATH
export GOPATH=/home/dwizzy/gopath

if go build -o /tmp/sloane-api-test ./cmd/api 2>&1; then
    pass "Go API compiles successfully"
    rm -f /tmp/sloane-api-test
else
    fail "Go API compilation failed"
fi

if go build -o /tmp/sloane-dispatcher-test ./cmd/dispatcher 2>&1; then
    pass "Go dispatcher compiles successfully"
    rm -f /tmp/sloane-dispatcher-test
else
    fail "Go dispatcher compilation failed"
fi

# Test 3: Check Python code
echo ""
echo "--- Checking Python code ---"

if [ -f "main.py" ]; then
    if python3 -m py_compile main.py 2>&1; then
        pass "Python scraper syntax is valid"
    else
        fail "Python scraper has syntax errors"
    fi
else
    fail "main.py not found"
fi

if [ -f "backfill.py" ]; then
    if python3 -m py_compile backfill.py 2>&1; then
        pass "Python backfill script syntax is valid"
    else
        fail "Python backfill script has syntax errors"
    fi
else
    fail "backfill.py not found"
fi

# Test 4: Check database schema
echo ""
echo "--- Checking database schema ---"

if [ -f "scripts/init.sql" ]; then
    pass "Database schema file exists"

    if grep -q "CREATE TABLE" scripts/init.sql; then
        pass "Schema contains table definitions"
    else
        fail "Schema missing table definitions"
    fi

    if grep -q "UNIQUE" scripts/init.sql; then
        pass "Schema includes UNIQUE constraints for deduplication"
    else
        warn "Schema may be missing deduplication constraints"
    fi
else
    fail "scripts/init.sql not found"
fi

# Test 5: Check PgBouncer configuration
echo ""
echo "--- Checking PgBouncer ---"

if [ -f "pgbouncer/pgbouncer.ini" ]; then
    pass "PgBouncer config exists"

    if grep -q "pool_mode" pgbouncer/pgbouncer.ini; then
        pass "PgBouncer pool mode configured"
    else
        warn "PgBouncer pool mode not explicitly set"
    fi
else
    fail "pgbouncer/pgbouncer.ini not found"
fi

# Test 6: Check Docker Compose services
echo ""
echo "--- Checking Docker Compose services ---"

if grep -q "postgres:" docker-compose.yml; then
    pass "PostgreSQL service defined"
else
    fail "PostgreSQL service not found"
fi

if grep -q "pgbouncer:" docker-compose.yml; then
    pass "PgBouncer service defined"
else
    fail "PgBouncer service not found"
fi

if grep -q "valkey:" docker-compose.yml; then
    pass "Valkey service defined"
else
    fail "Valkey service not found"
fi

if grep -q "api:" docker-compose.yml; then
    pass "API service defined"
else
    fail "API service not found"
fi

if grep -q "dispatcher:" docker-compose.yml; then
    pass "Dispatcher service defined"
else
    fail "Dispatcher service not found"
fi

if grep -q "backfill:" docker-compose.yml; then
    pass "Backfill service defined"
else
    fail "Backfill service not found"
fi

# Test 7: Check resource limits
echo ""
echo "--- Checking resource limits ---"

if grep -q "deploy:" docker-compose.yml; then
    pass "Resource limits configured"

    if grep -q "memory:" docker-compose.yml; then
        pass "Memory limits set"
    else
        warn "Memory limits not explicitly set"
    fi

    if grep -q "cpus:" docker-compose.yml; then
        pass "CPU limits set"
    else
        warn "CPU limits not explicitly set"
    fi
else
    warn "No resource limits configured (may cause system overload)"
fi

# Test 8: Check Dockerfiles
echo ""
echo "--- Checking Dockerfiles ---"

if [ -f "Dockerfile.api" ]; then
    pass "API Dockerfile exists"
else
    fail "Dockerfile.api not found"
fi

if [ -f "Dockerfile.backfill" ]; then
    pass "Backfill Dockerfile exists"
else
    fail "Dockerfile.backfill not found"
fi

# Test 9: Check Jawatch frontend
echo ""
echo "--- Checking Jawatch frontend ---"

if [ -d "../jawatch" ]; then
    pass "Jawatch directory exists"

    if [ -f "../jawatch/package.json" ]; then
        pass "package.json exists"

        if grep -q "bun" ../jawatch/package.json; then
            pass "Bun configured in package.json"
        else
            warn "Bun not explicitly configured (may use npm/yarn)"
        fi
    else
        fail "package.json not found"
    fi

    if [ -f "../jawatch/src/app/page.tsx" ]; then
        pass "Next.js app router structure exists"
    else
        fail "Next.js app structure not found"
    fi
else
    warn "Jawatch directory not found at ../jawatch (expected location)"
fi

# Test 10: Validate docker-compose syntax
echo ""
echo "--- Validating Docker Compose ---"

if docker compose config > /dev/null 2>&1; then
    pass "docker-compose.yml syntax is valid"
else
    fail "docker-compose.yml has syntax errors"
fi

# Summary
echo ""
echo "=== Test Summary ==="
echo -e "${GREEN}Passed:${NC} $TESTS_PASSED"
echo -e "${RED}Failed:${NC} $TESTS_FAILED"
echo ""

if [ $TESTS_FAILED -eq 0 ]; then
    echo -e "${GREEN}All tests passed! System is ready.${NC}"
    echo ""
    echo "To start the system:"
    echo "  1. docker compose up -d"
    echo "  2. docker compose --profile backfill run --rm backfill"
    echo "  3. docker compose --profile cron up -d"
    echo ""
    exit 0
else
    echo -e "${RED}Some tests failed. Please review and fix issues before starting.${NC}"
    exit 1
fi
