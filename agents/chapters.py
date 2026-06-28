"""Chapter standards — org-wide rules every squad member of a function follows.

In a human org a chapter is the horizontal function (backend/QA/frontend) with a
line manager. For agents there is no career/management. A chapter survives as:
  1. A shared standards document (this file) injected into agent instructions.
  2. A shared group-scoped memory (chapter_<x>) where learnings persist.

Standards are deliberately short — light, compact, lean (the sloane target
carries to all tribes). One agent per squad joins its chapter; chapters cross
all tribes.
"""
from __future__ import annotations

CHAPTER_BACKEND = """\
[Chapter Backend — org standard]
- Functions <50 lines, files <800 lines, no nesting >4.
- Validate all input at trust boundaries; parameterized queries only.
- Errors handled explicitly, never swallowed.
- Immutable: return new objects, don't mutate.
- YAGNI: no speculative abstraction. Delete over add.
- One repo per product; one PR per feature; CI green before merge.
"""

CHAPTER_QA = """\
[Chapter QA — org standard]
- Every change ships a check (test or assert) that fails if logic breaks.
- Test the behavior, not the implementation.
- Quality gate per scope: assert rows/contract before declaring PASS.
- Report PASS/FAIL with failing check names. Never auto-fix to green.
- 80%+ coverage on new logic; trivial one-liners need no test.
"""

CHAPTER_FRONTEND = """\
[Chapter Frontend — org standard]
- Semantic HTML first; no div-stack when an element exists.
- Design tokens as CSS variables; no hardcoded palette/spacing.
- Animate transform/opacity only (compositor-friendly).
- Explicit image dimensions; lazy below the fold.
- Accessible by default (keyboard, contrast, reduced-motion).
- Intentional design — not a default template.
"""


def chapter_for(role: str) -> str:
    """Return the standards block for a role ('backend'|'qa'|'frontend'|'lead')."""
    return {
        "backend": CHAPTER_BACKEND,
        "qa": CHAPTER_QA,
        "frontend": CHAPTER_FRONTEND,
        "lead": "",  # leads orchestrate, no function chapter
    }.get(role, "")


# group names in DB (agent_groups.name) — shared across tribes
def chapter_group(function: str) -> str:
    return f"chapter_{function}"  # chapter_backend, chapter_qa, chapter_frontend
