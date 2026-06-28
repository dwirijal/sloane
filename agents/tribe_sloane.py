"""Tribe sloane: 1 squad, sequential DAG.

Pipeline: lead (decompose) -> backend-py (fetch+write) -> qa (assert).
Each agent has a narrow scope + tools. The LLM orchestrates; tools do the
deterministic work. Tribe memory is locked to tribe_lead + squad_lead via
GroupMemoryService RBAC.

DevOps agent is YAGNI for the smoke milestone — add when the squad ships
real scrapers needing docker/cron wiring.
"""
from __future__ import annotations
import os

from google.adk.agents import Agent, SequentialAgent
from google.adk.models.lite_llm import LiteLlm

from sloane.agents.tools import fetch_tool, write_tool, assert_tool
from sloane.config.settings import ROUTER_BASE_URL, ROUTER_API_KEY, MODEL_LEAD, MODEL_WORKER

# suppress litellm telemetry noise (file-descriptor warnings)
try:
    import litellm
    litellm.success_callback = []
    litellm.failure_callback = []
    litellm.set_verbose = False
except Exception:
    pass


def _llm(model_id: str) -> LiteLlm:
    key = ROUTER_API_KEY or os.environ.get("OPENAI_API_KEY", "")
    return LiteLlm(
        model=f"openai/{model_id}",
        api_base=ROUTER_BASE_URL,
        api_key=key,
    )


LEAD_INSTRUCTION = """\
You are the sloane squad lead. Tribe: sloane (data ingestion for dwizzyOS).
Decompose the task into steps, then hand off. For the smoke task:
  1. backend fetches a source, writes entities to PG.
  2. qa asserts data quality.
State the source slug to use (stub-anime), then finish. One source for the smoke.
Scope: orchestration only. Do not call any tools yourself.
"""

BACKEND_INSTRUCTION = """\
You are the sloane backend engineer (Python). Scope: scraper + DB write ONLY.
Call the tool named `fetch_source` with source_slug="stub-anime".
Then call the tool named `write_entities_tool` with the returned entities list.
Do NOT assert — that is QA's job. Report the counts from write_entities_tool.
"""

QA_INSTRUCTION = """\
You are the sloane QA engineer. Scope: data quality gate ONLY.
Call the tool named `assert_quality` with source_slug="stub-anime".
Report exactly "PASS" or "FAIL" with the failing check names. If FAIL, state
what must be fixed (do not fix it). End with the single word PASS or FAIL.
"""


def build_tribe_sloane() -> SequentialAgent:
    """Construct the sloane squad as a sequential DAG."""
    lead = Agent(
        name="sloane_lead",
        model=_llm(MODEL_LEAD),
        instruction=LEAD_INSTRUCTION,
        description="sloane squad lead: decompose + handoff",
    )
    backend = Agent(
        name="sloane_backend_py",
        model=_llm(MODEL_WORKER),
        instruction=BACKEND_INSTRUCTION,
        description="backend: fetch + write",
        tools=[fetch_tool, write_tool],
    )
    qa = Agent(
        name="sloane_qa",
        model=_llm(MODEL_WORKER),
        instruction=QA_INSTRUCTION,
        description="QA: assert data quality",
        tools=[assert_tool],
    )
    return SequentialAgent(
        name="tribe_sloane",
        sub_agents=[lead, backend, qa],
        description="sloane tribe squad: lead->backend->qa sequential pipeline",
    )
