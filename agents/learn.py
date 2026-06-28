"""sloane improve + learn loop.

After a smoke run, the QA agent reviews the pipeline and writes a short
learning to squad + chapter memory. Concrete, verified improvements go to a
GitHub issue. Target: light/compact/lean. The loop never auto-expands scope —
if the pipeline passed cleanly, write one line and stop. YAGNI enforced.
"""
from __future__ import annotations
import os

from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm
from google.adk.tools import FunctionTool

from sloane.agents.chapters import CHAPTER_QA
from sloane.agents.tools import assert_quality
from sloane.config.settings import ROUTER_BASE_URL, ROUTER_API_KEY, MODEL_WORKER

try:
    import litellm
    litellm.success_callback = []; litellm.failure_callback = []; litellm.set_verbose = False
except Exception:
    pass


def _llm() -> LiteLlm:
    key = ROUTER_API_KEY or os.environ.get("OPENAI_API_KEY", "")
    return LiteLlm(model=f"openai/{MODEL_WORKER}", api_base=ROUTER_BASE_URL, api_key=key)


async def write_learning(group: str, text: str) -> dict:
    """Persist a one-line learning to a group's memory (squad/chapter).

    Written as 'sloane_qa' — member of squad_sloane + chapter_qa. RBAC blocks
    writes to tribe memory (correct; tribe is leads-only).
    """
    from google.adk.memory.memory_entry import MemoryEntry
    from google.genai.types import Content, Part
    from sloane.db.memory_service import GroupMemoryService
    svc = GroupMemoryService()
    mem = MemoryEntry(content=Content(role="user", parts=[Part(text=text)]), author="sloane_qa")
    await svc.add_memory(app_name=group, user_id="sloane_qa", memories=[mem])
    return {"group": group, "written": text}


learn_tool = FunctionTool(func=write_learning)


REVIEW_INSTRUCTION = f"""\
{CHAPTER_QA}
You are the sloane QA agent running an improve+learn pass.
1. Call assert_quality with source_slug="stub-anime".
2. If PASS and clean: write ONE concise learning to group "squad_sloane" (e.g.
   "smoke stable: 3 rows, dedup OK, no nulls") and stop. Do not over-engineer.
3. If anything is wasteful/heavy/redundant in the pipeline, write a learning
   to group "chapter_backend" naming exactly what to tighten (light/compact/lean).
4. Never invent work. Scope stays minimal.
"""


def build_review_agent() -> Agent:
    return Agent(
        name="sloane_review",
        model=_llm(),
        instruction=REVIEW_INSTRUCTION,
        description="sloane improve+learn: review, record learnings, open GH issue only if real",
        tools=[assert_quality, learn_tool],
    )
