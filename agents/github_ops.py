"""GitHub ops tools for agents. Forces full GH feature usage per squad.

Every squad must: issue -> branch -> commit -> push -> PR -> CI. These tools
wrap `gh` CLI + git subprocess so agents drive the full flow deterministically.

Precondition: `gh auth login` run on host (human one-time). Tools fail loud if
gh is unauthenticated — agents never bypass the gate.
"""
from __future__ import annotations
import subprocess
from google.adk.tools import FunctionTool


def _sh(cmd: list[str], cwd: str | None = None) -> str:
    """Run shell cmd, return stdout. Raise on non-zero (agents must see failures)."""
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f"{cmd[0]} failed: {r.stderr.strip() or r.stdout.strip()}")
    return r.stdout.strip()


def gh_create_issue(title: str, body: str, repo: str = "dwirijal/dwizzyOS") -> dict:
    """Open a GitHub issue describing the work. Returns {number, url}."""
    out = _sh(["gh", "issue", "create", "--repo", repo,
               "--title", title, "--body", body])
    return {"url": out, "repo": repo}


def gh_create_branch(branch: str, base: str = "main") -> dict:
    """Create + checkout a branch off base. Returns {branch}."""
    _sh(["git", "checkout", base])
    _sh(["git", "pull", "--ff-only"])
    _sh(["git", "checkout", "-b", branch])
    return {"branch": branch}


def gh_commit_push(message: str, files: list[str] | None = None) -> dict:
    """Stage files (or all), commit with message, push to current branch."""
    if files:
        _sh(["git", "add", *files])
    else:
        _sh(["git", "add", "-A"])
    _sh(["git", "commit", "-m", message])
    branch = _sh(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    _sh(["git", "push", "-u", "origin", branch])
    return {"branch": branch, "message": message}


def gh_create_pr(title: str, body: str, base: str = "main") -> dict:
    """Open a PR from current branch into base. Returns {url}."""
    head = _sh(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    out = _sh(["gh", "pr", "create", "--title", title, "--body", body,
               "--base", base, "--head", head])
    return {"url": out, "head": head, "base": base}


def gh_check_ci(pr_url: str | None = None) -> dict:
    """Check CI status for current branch / PR. Returns {checks, passing}."""
    branch = _sh(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    try:
        out = _sh(["gh", "pr", "checks", branch] + (["--repo", "dwirijal/dwizzyOS"]))
        passing = "pass" in out.lower() and "fail" not in out.lower()
        return {"branch": branch, "checks": out, "passing": passing}
    except RuntimeError as e:
        return {"branch": branch, "checks": str(e), "passing": False}


# ADK FunctionTools
gh_issue_tool = FunctionTool(func=gh_create_issue)
gh_branch_tool = FunctionTool(func=gh_create_branch)
gh_push_tool = FunctionTool(func=gh_commit_push)
gh_pr_tool = FunctionTool(func=gh_create_pr)
gh_ci_tool = FunctionTool(func=gh_check_ci)
