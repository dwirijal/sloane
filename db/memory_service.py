"""Custom ADK BaseMemoryService backed by Postgres + pgvector.

Group-scoped RBAC:
  - app_name  = group name (e.g. "squad-sloane", "guild-perf", "tribe-sloane")
  - user_id   = agent_id (the writer / searcher)

Write: agent must be a member of the group (role any). Tribe groups require
  tribe_lead or squad_lead role (enforced in DB view + checked here).
Read:  uses v_memory_readable view — tribe memory only visible to tribe_lead +
  squad_lead; squad/chapter/guild visible to all members.

Embeddings are optional (vector column nullable). Keyword (ILIKE) search used
until an embedding provider is wired. ponytail: add embeddings when RAG needs
semantic recall, not before.
"""
from __future__ import annotations
from collections.abc import Mapping, Sequence

import psycopg
from google.adk.memory.base_memory_service import SearchMemoryResponse
from google.adk.memory.memory_entry import MemoryEntry
from google.adk.memory.base_memory_service import BaseMemoryService
from google.adk.sessions import Session
from google.adk.events import Event
from google.genai.types import Part

from sloane.config.settings import pg_dsn


class GroupMemoryService(BaseMemoryService):
    """RBAC-enforced, group-scoped memory on pgvector."""

    def __init__(self, dsn: str | None = None) -> None:
        self._dsn = dsn or pg_dsn()

    # ---- helpers -------------------------------------------------------
    def _group_id(self, cur, app_name: str) -> int | None:
        row = cur.execute("SELECT id FROM agent_groups WHERE name=%s", (app_name,)).fetchone()
        return row[0] if row else None

    def _can_write(self, cur, agent_id: str, group_id: int) -> bool:
        """Member of the group? Tribe groups need tribe_lead/squad_lead."""
        row = cur.execute(
            "SELECT g.kind, am.role IS NOT NULL AS is_member, am.role "
            "FROM agent_groups g LEFT JOIN agent_memberships am "
            "  ON am.group_id=g.id AND am.agent_id=%s "
            "WHERE g.id=%s",
            (agent_id, group_id),
        ).fetchone()
        if not row or not row[1]:
            return False
        kind, _, role = row
        if kind == "tribe":
            return role in ("tribe_lead", "squad_lead")
        return True

    # ---- BaseMemoryService interface ----------------------------------
    async def add_memory(self, *, app_name: str, user_id: str,
                         memories: Sequence[MemoryEntry],
                         custom_metadata: Mapping[str, object] | None = None) -> None:
        with psycopg.connect(self._dsn) as conn, conn.cursor() as cur:
            gid = self._group_id(cur, app_name)
            if gid is None:
                raise ValueError(f"unknown group: {app_name}")
            if not self._can_write(cur, user_id, gid):
                raise PermissionError(f"{user_id} cannot write to group {app_name}")
            for mem in memories:
                text = " ".join(p.text or "" for p in (mem.content.parts or []) if p)
                meta = dict(custom_metadata or {}) | dict(mem.custom_metadata or {})
                cur.execute(
                    "INSERT INTO agent_memory (group_id, author, content, metadata) "
                    "VALUES (%s,%s,%s,%s)",
                    (gid, mem.author or user_id, text, psycopg.types.json.Json(meta)),
                )
            conn.commit()

    async def add_events_to_memory(self, *, app_name: str, user_id: str,
                                   events: Sequence[Event],
                                   session_id: str | None = None,
                                   custom_metadata: Mapping[str, object] | None = None) -> None:
        # ponytail: not all services implement this; flatten events to text memories.
        memories = []
        for ev in events:
            if not ev.content or not ev.content.parts:
                continue
            text = " ".join(p.text or "" for p in ev.content.parts if p)
            if not text.strip():
                continue
            memories.append(MemoryEntry(content=ev.content, author=ev.author or user_id))
        if memories:
            await self.add_memory(app_name=app_name, user_id=user_id,
                                  memories=memories, custom_metadata=custom_metadata)

    async def add_session_to_memory(self, session: Session) -> None:
        # app_name=user_id on Session; route via add_events_to_memory.
        await self.add_events_to_memory(
            app_name=session.app_name, user_id=session.user_id,
            events=session.events,
        )

    async def search_memory(self, *, app_name: str, user_id: str,
                            query: str) -> SearchMemoryResponse:
        # RBAC: only rows the agent may read in THIS group (app_name).
        with psycopg.connect(self._dsn) as conn, conn.cursor() as cur:
            rows = cur.execute(
                "SELECT m.content, m.author, m.created_at::text "
                "FROM v_memory_readable vm "
                "JOIN agent_memory m ON m.id = vm.id "
                "JOIN agent_groups g ON g.id = m.group_id "
                "WHERE vm.agent_id=%s AND g.name=%s AND m.content ILIKE %s "
                "ORDER BY m.created_at DESC LIMIT 20",
                (user_id, app_name, f"%{query}%"),
            ).fetchall()
        entries = [
            MemoryEntry(content=_text_content(r[0]), author=r[1], timestamp=r[2])
            for r in rows
        ]
        return SearchMemoryResponse(memories=entries)


def _text_content(text: str):
    """Build a genai Content from plain text (for MemoryEntry)."""
    from google.genai.types import Content
    return Content(role="user", parts=[Part(text=text)])
