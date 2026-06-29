"""Shared HTTP client + selectors for samehadaku source.

v2.samehadaku.how is plain WordPress — no Cloudflare challenge, no JS gating.
httpx with a browser UA fetches every page directly (verified 2026-06-29).
"""
from __future__ import annotations

import httpx

BASE_URL = "https://v2.samehadaku.how"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}

# Selectors verified live 2026-06-29.
SEL_SERIES_ANCHOR = ".thumb a[itemprop='url']"     # list pages: href=/anime/{slug}
SEL_COVER_IMG = "img.npws"                          # within anchor
SEL_INFOX = ".infox"                                # series metadata block
SEL_SYNOPSIS = ".entry-content, [itemprop='description'], .sinopsis"
SEL_DOWNLOAD_BLOCK = "div.download-eps"            # episode + batch download container


def client() -> httpx.Client:
    """Fresh httpx client. Caller owns lifecycle (with-statement)."""
    return httpx.Client(headers=HEADERS, timeout=20, follow_redirects=True)
