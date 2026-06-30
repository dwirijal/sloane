"""Shared HTTP client + selectors for the anichin source.

anichin.moe is plain WordPress — no Cloudflare challenge, no JS gating, but the
RSS /feed/ is disabled (returns 500). httpx with a browser UA fetches every page
directly (verified 2026-06-30).
"""
from __future__ import annotations

import httpx

BASE_URL = "https://anichin.moe"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}

# Sidebar .subSchh appears on every page (6 latest series) and would pollute
# list/directory parsing — strip it before scanning for series anchors.
SEL_SIDEBAR = ".subSchh"

def client() -> httpx.Client:
    """Fresh httpx client. Caller owns lifecycle (with-statement)."""
    return httpx.Client(headers=HEADERS, timeout=20, follow_redirects=True)
