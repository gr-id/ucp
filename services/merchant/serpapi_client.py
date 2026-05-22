"""SerpAPI Google Shopping wrapper for the 2nd PoC.

Looks up real products from the four UCP-live merchants (Walmart, Target,
Wayfair, Etsy). Maintains a 1-hour in-memory cache to stay well under the
SerpAPI free tier (250 queries/month).

Requires the `SERPAPI_KEY` environment variable. If unset, `search()` returns
an empty list and logs a warning rather than raising — this lets the rest of
the system fail gracefully with a useful UI message.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import time
from typing import Any

import httpx

log = logging.getLogger("serpapi_client")

SERPAPI_URL = "https://serpapi.com/search.json"
CACHE_TTL_SECONDS = 3600

# The four UCP-live merchants per Google's 2026.01 announcement and updates.
LIVE_MERCHANTS = ("walmart", "target", "wayfair", "etsy")

# (query, price_from_cents, price_to_cents, merchants_tuple) -> (expiry_ts, results)
_CACHE: dict[tuple[str, int, int, tuple[str, ...]], tuple[float, list[dict]]] = {}


def normalize_source(s: str | None) -> str:
    """Normalize a SerpAPI `source` value to one of the live merchant slugs.

    Handles variations like 'Walmart.com', 'Walmart - Seller', 'Target', etc.
    Returns an empty string if no live merchant matches.
    """
    if not s:
        return ""
    cleaned = s.lower().replace(".com", "").replace("-", " ").strip()
    for m in LIVE_MERCHANTS:
        # Match as a word-ish prefix to avoid false positives.
        if cleaned == m or cleaned.startswith(m + " ") or cleaned.startswith(m + " -"):
            return m
    # Last resort: substring match
    for m in LIVE_MERCHANTS:
        if m in cleaned:
            return m
    return ""


_PRICE_RE = re.compile(r"\$?\s*([\d,]+(?:\.\d+)?)")


def _parse_price_cents(value: Any) -> int | None:
    """Convert SerpAPI's price representation to integer cents."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(round(float(value) * 100))
    if not isinstance(value, str):
        return None
    m = _PRICE_RE.search(value.replace(",", ""))
    if not m:
        return None
    try:
        return int(round(float(m.group(1).replace(",", "")) * 100))
    except ValueError:
        return None


def _stable_product_id(link: str | None, title: str) -> str:
    seed = (link or title or "").encode("utf-8")
    return "sku_" + hashlib.sha1(seed).hexdigest()[:12]


def normalize(r: dict) -> dict | None:
    """Convert one SerpAPI shopping result into our internal product dict.

    Returns None if the result cannot be matched to a live merchant or has no
    parseable price.
    """
    source = normalize_source(r.get("source"))
    if not source:
        return None
    price_cents = _parse_price_cents(r.get("extracted_price")) or _parse_price_cents(r.get("price"))
    if not price_cents:
        return None
    title = (r.get("title") or "").strip()
    if not title:
        return None
    return {
        "id": _stable_product_id(r.get("link") or r.get("product_link"), title),
        "title": title,
        "brand": r.get("source", "").strip(),
        "source_merchant": source,
        "category": "shopping",  # SerpAPI doesn't categorize uniformly
        "price_cents": price_cents,
        "currency": "USD",
        "description": (r.get("snippet") or title)[:300],
        "image_url": r.get("thumbnail"),
        "product_url": r.get("product_link") or r.get("link"),
        "rating": r.get("rating"),
        "reviews_count": r.get("reviews"),
    }


def _resolve_key(api_key: str | None) -> str | None:
    """Caller-provided key wins; otherwise fall back to SERPAPI_KEY env."""
    if api_key:
        return api_key
    return os.environ.get("SERPAPI_KEY")


def _serpapi_call(query: str, from_cents: int, to_cents: int, api_key: str) -> list[dict]:
    """Single SerpAPI call. Returns raw shopping_results list (or []) on failure."""
    params: dict[str, Any] = {
        "engine": "google_shopping",
        "q": query,
        "gl": "us",
        "hl": "en",
        "api_key": api_key,
    }
    if to_cents:
        ppr_min = max(0, from_cents // 100)
        ppr_max = max(1, to_cents // 100)
        params["tbs"] = f"mr:1,price:1,ppr_min:{ppr_min},ppr_max:{ppr_max}"
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.get(SERPAPI_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        log.warning("SerpAPI request failed for q=%r: %s", query, e)
        return []
    return (
        data.get("shopping_results")
        or data.get("inline_shopping_results")
        or data.get("immersive_products")
        or []
    )


def search(
    query: str,
    from_cents: int = 0,
    to_cents: int = 10_000_00,
    merchants: tuple[str, ...] | list[str] | None = None,
    api_key: str | None = None,
) -> list[dict]:
    """Search Google Shopping (via SerpAPI) restricted to the given merchants.

    Strategy: one query per selected merchant with the merchant's name appended
    so Google's ranking actually returns that merchant's listings. We then
    keep only results whose `source` matches the merchant we asked for.

    Caches each (query, from, to, merchants, key-hash) tuple for 1 hour.

    `api_key`, if provided, overrides the server's SERPAPI_KEY env — this lets
    multiple users of a hosted deployment each consume their own quota.
    """
    merchants_t = tuple(sorted(set(merchants))) if merchants else LIVE_MERCHANTS
    resolved_key = _resolve_key(api_key)
    # Include a short hash of the key in the cache key so cached results from
    # one user's quota don't leak to another's. Empty string for the no-key case.
    key_tag = ""
    if resolved_key:
        import hashlib as _h
        key_tag = _h.sha1(resolved_key.encode()).hexdigest()[:8]
    cache_key = (query.strip().lower(), from_cents, to_cents, merchants_t, key_tag)

    now = time.time()
    cached = _CACHE.get(cache_key)
    if cached and cached[0] > now:
        return cached[1]

    if not resolved_key:
        log.warning("SERPAPI_KEY not set — returning empty results")
        _CACHE[cache_key] = (now + 60, [])
        return []

    products: list[dict] = []
    seen_ids: set[str] = set()

    for merchant in merchants_t:
        # Per-merchant query: append the merchant name to the user's query so
        # Google Shopping returns that merchant's catalog. The `site:` operator
        # is not honored by google_shopping; appending the merchant name is the
        # reliable workaround. We then keep only results whose `source` matches.
        per_query = f"{query.strip()} {merchant}".strip()
        raw_results = _serpapi_call(per_query, from_cents, to_cents, resolved_key)

        for r in raw_results:
            norm = normalize(r)
            if norm is None:
                continue
            if norm["source_merchant"] != merchant:
                # Strict source filter — drop any result not from the merchant we asked for.
                continue
            if norm["price_cents"] < from_cents or norm["price_cents"] > to_cents:
                continue
            if norm["id"] in seen_ids:
                continue
            seen_ids.add(norm["id"])
            products.append(norm)

    _CACHE[cache_key] = (now + CACHE_TTL_SECONDS, products)
    return products


def get_by_id(product_id: str) -> dict | None:
    """Look up a previously-seen product by its stable id (cache-only)."""
    for _expiry, products in _CACHE.values():
        for p in products:
            if p["id"] == product_id:
                return p
    return None


def cache_stats() -> dict:
    """Debug introspection — useful in the smoke test."""
    return {
        "entries": len(_CACHE),
        "products": sum(len(v[1]) for v in _CACHE.values()),
    }
