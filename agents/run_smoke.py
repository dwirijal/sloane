"""Run the sloane tribe smoke: lead->backend->qa via ADK Runner.

Wires GroupMemoryService (RBAC) as the runner's memory. Prints each agent's
final text. Exit 0 on QA PASS, 1 on FAIL.
"""
from __future__ import annotations
import asyncio
import os
import sys

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai.types import Content, Part

from sloane.agents.tribe_sloane import build_tribe_sloane
from sloane.config.settings import ROUTER_API_KEY
from sloane.db.memory_service import GroupMemoryService

TASK = (
    "Smoke task for tribe sloane: ingest the 'stub-anime' source end-to-end "
    "(fetch, write to PG) then run QA. Use stub-anime."
)


async def main() -> int:
    if not ROUTER_API_KEY and not os.environ.get("OPENAI_API_KEY"):
        print("ERROR: set OPENAI_API_KEY (9router key)", file=sys.stderr)
        return 2
    tribe = build_tribe_sloane()
    sessions = InMemorySessionService()
    memory = GroupMemoryService()
    runner = Runner(
        agent=tribe, app_name="tribe-sloane",
        session_service=sessions, memory_service=memory,
    )
    session = await sessions.create_session(app_name="tribe-sloane", user_id="operator")
    qa_text = ""
    async for ev in runner.run_async(
        user_id="operator", session_id=session.id,
        new_message=Content(role="user", parts=[Part(text=TASK)]),
    ):
        who = ev.author or "?"
        if ev.content and ev.content.parts:
            for p in ev.content.parts:
                if p.text:
                    print(f"[{who}] {p.text.strip()[:300]}")
                    if who == "sloane_qa":
                        qa_text += p.text
    passed = "PASS" in qa_text.upper() and "FAIL" not in qa_text.upper()
    print("\nSMOKE:", "PASS ✅" if passed else "FAIL ❌")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
