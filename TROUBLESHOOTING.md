# Troubleshooting Guide

## Docker Socket Permission Denied

**Error:** `permission denied while trying to connect to the docker API at unix:///var/run/docker.sock`

### Solution 1: Add User to Docker Group (Recommended)
```bash
# Add your user to the docker group
sudo usermod -aG docker $USER

# Apply group changes (log out and log back in, or run)
newgrp docker

# Verify
docker ps
```

### Solution 2: Run Docker Commands with Sudo
```bash
sudo docker compose up -d
```
*Note: Requires password entry each time.*

### Solution 3: Fix Socket Permissions (Temporary)
```bash
sudo chmod 666 /var/run/docker.sock
```
*Warning: This is insecure and should only be used for local development.*

---

## Alternative: Run Scraper Without Docker

If Docker is unavailable, you can run the Python scraper directly:

### Prerequisites
```bash
# Install Python dependencies
cd /home/dwizzy/sloane
python3 -m venv venv
source venv/bin/activate
pip install -r scraper/requirements.txt
```

### Run Scraper Directly
```bash
# Ensure PostgreSQL is accessible (update DATABASE_URL in .env if needed)
export DATABASE_URL="postgresql://sloane:password@localhost:5432/sloane"

# Run the scraper
python main.py
```

### Run Backfill Directly
```bash
python backfill.py
```

---

## Database Connection Issues

**Error:** `Multiple exceptions: [Errno 111] Connect call failed`

### Solutions
1. Ensure PostgreSQL is running: `sudo systemctl status postgresql`
2. Check connection string in `.env` or environment variables
3. Verify PgBouncer is running if using connection pooling
4. Test connection manually: `psql -h localhost -U sloane -d sloane`

---

## API Not Responding

**Error:** `ECONNREFUSED` or `fetch failed`

### Solutions
1. Verify API container is running: `docker ps | grep sloane-api`
2. Check API logs: `docker logs sloane-api`
3. Ensure correct port mapping (default: `8080:8080`)
4. Test locally: `curl http://localhost:8080/health`

---

## Jawatch Build Failures

**Error:** TypeScript errors or missing modules

### Solutions
1. Clear Next.js cache: `rm -rf .next`
2. Reinstall dependencies: `rm -rf node_modules && npm install`
3. Check Node.js version: `node --version` (requires 18+)
4. Run type check: `npm run typecheck`