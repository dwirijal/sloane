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
2. **ROUTER_API_KEY** (LLM for merge fuzzy-match + Jikan-free enrich). Create:
   ```
   mkdir -p ~/.config/sloane
   echo "ROUTER_API_KEY=your-9router-key" > ~/.config/sloane/ingest.env
   ```
   (The 9router base URL is set in the service: `http://192.168.100.6:20128/v1`.)
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
PYTHONPATH=/home/dwirijal/Projects/dwizzyOS:/home/dwirijal/Projects/dwizzyOS/dwizzyOS-HQ \
DOS_PGB_URL=postgresql://dwizzy:kultivasimusemangatku@localhost:6432/dwizzyos \
/home/dwirijal/Projects/dwizzyOS/.venv-adk/bin/python -m sloane.ingest samehadaku --max-new 1
```

An anichin manual one-off (same pattern, `anichin` source arg):
```
PYTHONPATH=/home/dwirijal/Projects/dwizzyOS:/home/dwirijal/Projects/dwizzyOS/dwizzyOS-HQ \
DOS_PGB_URL=postgresql://dwizzy:kultivasimusemangatku@localhost:6432/dwizzyos \
/home/dwirijal/Projects/dwizzyOS/.venv-adk/bin/python -m sloane.ingest anichin --max-new 1
```

## Alternative: run timers on the homeserver

The homeserver does NOT currently have a sloane checkout, venv, or
dwizzyOS-HQ. If you'd rather run the timers there (no tunnel — `DOS-pgb` is
local at `127.0.0.1:6432`), clone sloane + HQ there, create a venv with
bs4/httpx/psycopg, and change the service `Environment=DOS_PGB_URL=...@127.0.0.1:6432/...`
+ drop the tunnel dependency. Cleaner for 24/7 (no SSH tunnel to babysit).
