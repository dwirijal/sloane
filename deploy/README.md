# sloane deploy units

systemd units for the samehadaku ingest runner. Timers live on the **dev
machine** (where sloane + its venv + dwizzyOS-HQ `shared/` exist); the DB is
reached over a persistent SSH tunnel to the homeserver's pgbouncer.

## Units

| Unit | Purpose |
|---|---|
| `sloane-db-tunnel.service` | Persistent SSH tunnel: local `:6432` → homeserver `DOS-pgb` (`127.0.0.1:6432`). `Restart=always`. |
| `sloane-samehadaku-ingest.timer` | Every 2h → `sloane-samehadaku-ingest.service` (feed-delta ingest). |
| `sloane-samehadaku-discover.timer` | Daily 05:00 → `sloane-samehadaku-discover.service` (new-series sweep). |
| `sloane-anichin-ingest.timer` | Every 2h → `sloane-anichin-ingest.service` (latest-update delta ingest). |
| `sloane-anichin-discover.timer` | Daily 05:00 → `sloane-anichin-discover.service` (A-Z new-series sweep). |

The ingest/discover services `Requires=sloane-db-tunnel.service`, so the tunnel
must be up for them to run.

## Prerequisites

1. **SSH to homeserver without a password** (the tunnel runs unattended):
   ```
   ssh-copy-id dwizzy@192.168.100.6
   ssh dwizzy@192.168.100.6 true   # should not prompt
   ```
2. **`~/.config/sloane/ingest.env`** (DB password + LLM key — not committed). Create:
   ```
   mkdir -p ~/.config/sloane
   cat > ~/.config/sloane/ingest.env <<'EOF'
   DOS_PGB_URL=postgresql://dwizzy:<DB_PASSWORD>@192.168.100.6:6432/dwizzyos
   ROUTER_API_KEY=your-9router-key
   EOF
   chmod 600 ~/.config/sloane/ingest.env
   ```
   On the homeserver the DB password is the docker secret — populate it with:
   `PW=$(docker exec DOS-pg cat /run/secrets/dos_pg_password); sed -i "s/<DB_PASSWORD>/$PW/" ~/.config/sloane/ingest.env`
   (The 9router base URL is set inline in the service: `http://192.168.100.6:20128/v1`.
   The `.service` files **require** this file — missing it, systemd refuses to start.)
3. **Python venv + deps** already at
   `/home/dwirijal/Projects/dwizzyOS/.venv-adk` (bs4, httpx, psycopg).

## Install (system units — needs sudo for the tunnel; user units for the rest)

```
sudo cp deploy/sloane-db-tunnel.service /etc/systemd/system/
mkdir -p ~/.config/systemd/user
cp deploy/sloane-samehadaku-ingest.service deploy/sloane-samehadaku-ingest.timer \
   deploy/sloane-samehadaku-discover.service deploy/sloane-samehadaku-discover.timer \
   deploy/sloane-anichin-ingest.service deploy/sloane-anichin-ingest.timer \
   deploy/sloane-anichin-discover.service deploy/sloane-anichin-discover.timer \
   ~/.config/systemd/user/

sudo systemctl daemon-reload
sudo systemctl enable --now sloane-db-tunnel.service
systemctl --user daemon-reload
systemctl --user enable --now sloane-samehadaku-ingest.timer
systemctl --user enable --now sloane-samehadaku-discover.timer
systemctl --user enable --now sloane-anichin-ingest.timer
systemctl --user enable --now sloane-anichin-discover.timer
```

> Note: the tunnel is a system service (needs the host network namespace +
> early boot); the two ingest timers are user services. If you'd rather run
> everything as user units, drop the tunnel's `multi-user` install and run it
> as a user service instead — but then it won't start before login.

## Verify

```
systemctl --user list-timers | grep samehadaku     # both timers scheduled
systemctl --user list-timers | grep anichin        # both timers scheduled
systemctl status sloane-db-tunnel.service          # tunnel active
journalctl --user -u sloane-samehadaku-ingest.service -f   # live ingest logs
journalctl --user -u sloane-anichin-ingest.service -f      # live ingest logs
```

A manual one-off (no timers needed):
```
set -a; . ~/.config/sloane/ingest.env; set +a
PYTHONPATH=$HOME/dwizzyOS:$HOME/dwizzyOS-HQ \
$HOME/dwizzyOS/.venv-adk/bin/python -m sloane.ingest samehadaku --max-new 1
```

An anichin manual one-off (same pattern, `anichin` source arg):
```
set -a; . ~/.config/sloane/ingest.env; set +a
PYTHONPATH=$HOME/dwizzyOS:$HOME/dwizzyOS-HQ \
$HOME/dwizzyOS/.venv-adk/bin/python -m sloane.ingest anichin --max-new 1
```
(`set -a`/`.` are shell builtins — no new dep, robust against special chars in values.)

## Running timers on the homeserver (primary deploy target)

The homeserver already has `~/dwizzyOS/.venv-adk` (httpx/bs4/psycopg),
`~/dwizzyOS-HQ` (shared/), and the Docker `DOS-pg`+`DOS-pgb` containers — so
the DB is **local** and no SSH tunnel is needed (cleaner for 24/7). The deploy
units use `%h`-relative paths and `After=docker.service` (no tunnel dependency).

To deploy there:
```
ssh dwizzy@192.168.100.6
rm -rf ~/sloane   # stale stub
git clone git@github.com:dwirijal/sloane.git ~/dwizzyOS/sloane
# create ingest.env per Prerequisites step 2 (password = docker secret)
cp ~/dwizzyOS/sloane/deploy/sloane-*.service ~/dwizzyOS/sloane/deploy/sloane-*.timer \
   ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now sloane-anichin-ingest.timer sloane-anichin-discover.timer \
   sloane-samehadaku-ingest.timer sloane-samehadaku-discover.timer
```
(homeserver login shell is fish — wrap multi-command steps in `bash -lc '...'` over SSH.)

