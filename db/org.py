"""Org bootstrap: tribes, squads, chapters, guilds seeded into agent_groups.

Idempotent. Run once at startup. Maps the org structure to group rows so
GroupMemoryService RBAC applies. tribe-* groups are locked to tribe_lead +
squad_lead; chapter_*/guild_* writable by members.
"""
from __future__ import annotations
import psycopg

from sloane.config.settings import pg_dsn

# org: tribe -> squads; each squad has role -> agent_id
ORG: dict[str, dict[str, dict[str, str]]] = {
    "sloane": {
        "squad_sloane": {
            "lead": "sloane_lead",
            "backend": "sloane_backend_py",
            "qa": "sloane_qa",
        },
    },
    "avicenna": {
        "squad_avicenna": {
            "lead": "avicenna_lead",
            "backend": "avicenna_backend_go",
            "qa": "avicenna_qa",
            "frontend": "avicenna_frontend",
        },
    },
}

CHAPTERS = ["backend", "qa", "frontend"]
GUILDS = ["web_perf", "cloudflare", "best_practice"]  # persona guilds (memory only)


def bootstrap_org(dsn: str | None = None) -> None:
    dsn = dsn or pg_dsn()
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        # chapters + guilds (org-wide)
        for ch in CHAPTERS:
            cur.execute(
                "INSERT INTO agent_groups (name, kind) VALUES (%s,'chapter') "
                "ON CONFLICT (name) DO NOTHING", (f"chapter_{ch}",))
        for g in GUILDS:
            cur.execute(
                "INSERT INTO agent_groups (name, kind) VALUES (%s,'guild') "
                "ON CONFLICT (name) DO NOTHING", (f"guild_{g}",))
        # tribes + squads + memberships
        for tribe, squads in ORG.items():
            cur.execute(
                "INSERT INTO agent_groups (name, kind) VALUES (%s,'tribe') "
                "ON CONFLICT (name) DO NOTHING", (f"tribe_{tribe}",))
            tribe_id = cur.execute(
                "SELECT id FROM agent_groups WHERE name=%s", (f"tribe_{tribe}",)).fetchone()[0]
            for squad, roles in squads.items():
                cur.execute(
                    "INSERT INTO agent_groups (name, kind, parent_id) VALUES (%s,'squad',%s) "
                    "ON CONFLICT (name) DO NOTHING", (squad, tribe_id))
                sq_id = cur.execute(
                    "SELECT id FROM agent_groups WHERE name=%s", (squad,)).fetchone()[0]
                for role, agent_id in roles.items():
                    role_in_squad = "squad_lead" if role == "lead" else "member"
                    cur.execute(
                        "INSERT INTO agent_memberships (agent_id, group_id, role) "
                        "VALUES (%s,%s,%s) ON CONFLICT (agent_id, group_id) DO NOTHING",
                        (agent_id, sq_id, role_in_squad))
                    # tribe membership: leads only can write; all members read (view filters)
                    cur.execute(
                        "INSERT INTO agent_memberships (agent_id, group_id, role) "
                        "VALUES (%s,%s,%s) ON CONFLICT (agent_id, group_id) DO NOTHING",
                        (agent_id, tribe_id, role_in_squad))
                    # chapter membership (function role)
                    if role in CHAPTERS:
                        ch_id = cur.execute(
                            "SELECT id FROM agent_groups WHERE name=%s",
                            (f"chapter_{role}",)).fetchone()[0]
                        cur.execute(
                            "INSERT INTO agent_memberships (agent_id, group_id, role) "
                            "VALUES (%s,%s,'member') ON CONFLICT (agent_id, group_id) DO NOTHING",
                            (agent_id, ch_id))
        conn.commit()
