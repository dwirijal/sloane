# sloane deploy

Sloane runs as two Docker containers managed by Gebelin (`/home/dwizzy/dwizzyOS/Gebelin/docker-compose.yml`):

- `sloane-web` — read API (`sloane.karepmuwes.my.id` → `:8080`), `sloane_ro` SELECT-only role.
- `sloane-worker` — ingest loop + HTTP kick (`:8081` backend-only), writer role.

## Bringup

```bash
cd /home/dwizzy/dwizzyOS/Gebelin
docker compose up -d sloane-web sloane-worker
```

Secrets + DSN via `../.secrets/{sloane_ro_pgb_url,dos_pgb_url,dos_vk_url}` (env_file). Migrations run on worker startup (`ensure_schema`).

## Manual one-off (outside compose)

```bash
docker compose run --rm sloane-worker python -m sloane.ingest samehadaku --max-new 1
```

## Verify

```bash
curl -sf http://sloane-web:8080/v1/health   # from caddy container → 200
docker logs dwizzyos-sloane-worker           # ingest cycle JSON
```
