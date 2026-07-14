"""Validate / canonicalize customer-provided Google review links."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

WRITEREVIEW = "https://search.google.com/local/writereview?placeid={pid}"

# Accepted "already valid" review-link hosts/patterns.
_G_PAGE = re.compile(r"https?://g\.page/r/[A-Za-z0-9_-]+/review", re.I)
_WRITEREVIEW = re.compile(
    r"https?://search\.google\.com/local/writereview\?placeid=([A-Za-z0-9_-]+)", re.I)
_SHARE = re.compile(r"https?://share\.google/[A-Za-z0-9_-]+", re.I)
_MAPS_APP = re.compile(r"https?://maps\.app\.goo\.gl/[A-Za-z0-9_-]+", re.I)

_URL_IN_TEXT = re.compile(r"https?://\S+", re.I)


@dataclass
class LinkResult:
    valid: bool
    canonical: str = ""
    place_id: str = ""
    needs_resolution: bool = False   # e.g. share.google short link needs a network hop
    reason: str = ""


def canonicalize(raw: str, resolver=None) -> LinkResult:
    """Extract and validate a review URL from possibly-noisy text.

    ``resolver`` is an optional callable(url)->final_url used to expand short
    links (share.google / maps.app.goo.gl). Kept injectable so the core stays
    offline-testable.
    """
    if not raw:
        return LinkResult(False, reason="empty")

    m = _URL_IN_TEXT.search(raw)               # strip stray company-name prefix
    if not m:
        return LinkResult(False, reason="no url in text")
    url = m.group(0).rstrip(").,]")

    if _G_PAGE.match(url):
        return LinkResult(True, canonical=url)

    wm = _WRITEREVIEW.match(url)
    if wm:
        pid = wm.group(1)
        return LinkResult(True, canonical=WRITEREVIEW.format(pid=pid), place_id=pid)

    if _SHARE.match(url) or _MAPS_APP.match(url):
        if resolver is None:
            return LinkResult(False, needs_resolution=True, reason="short link", canonical=url)
        final = resolver(url)
        if final and final != url:
            return canonicalize(final, resolver=None)
        return LinkResult(False, reason="could not resolve short link", canonical=url)

    return LinkResult(False, reason="unrecognized link format", canonical=url)


def link_from_place_id(place_id: str) -> str:
    return WRITEREVIEW.format(pid=place_id)


def http_resolver(url: str, timeout: float = 8.0) -> str:
    """Follow redirects for short links (share.google / maps.app.goo.gl).
    Returns the final URL, or '' on failure."""
    import requests
    try:
        r = requests.get(url, allow_redirects=True, timeout=timeout,
                         headers={"User-Agent": "Mozilla/5.0"})
        return r.url or ""
    except Exception:
        return ""
