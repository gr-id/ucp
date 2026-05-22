"""UCP catalog — mock (in-memory) or live (SerpAPI Google Shopping).

The active source is chosen by the `UCP_CATALOG_MODE` environment variable:
  - `mock` (default): the original five hardcoded products from the 1st PoC.
    Each carries a `source_merchant` tag so the 2nd-PoC UI can still show
    merchant badges in offline development.
  - `serpapi`: live products from Walmart / Target / Wayfair / Etsy via the
    SerpAPI Google Shopping API. Requires `SERPAPI_KEY`.
"""

from __future__ import annotations

import os

from services.merchant import serpapi_client
from services.shared.mandates import LineItem

# ------------------------- mock products -------------------------

# Tagged with source_merchant so the 2nd-PoC UI behaves the same way in mock
# mode (badges, merchant filter respected).
_MOCK_PRODUCTS: list[dict] = [
    {
        "id": "sku_runner_w_01",
        "title": "Cloudstride White Runners",
        "brand": "Aerolift",
        "color": "white",
        "category": "running-shoes",
        "price_cents": 12900,
        "currency": "USD",
        "description": "Lightweight white running shoes with breathable mesh upper.",
        "image_url": None,
        "source_merchant": "walmart",
        "product_url": "https://walmart.com/example/sku_runner_w_01",
    },
    {
        "id": "sku_runner_w_02",
        "title": "Pacelane Pro White",
        "brand": "Strideworks",
        "color": "white",
        "category": "running-shoes",
        "price_cents": 14500,
        "currency": "USD",
        "description": "Marathon-ready white runners, carbon plate, 7mm drop.",
        "image_url": None,
        "source_merchant": "target",
        "product_url": "https://target.com/example/sku_runner_w_02",
    },
    {
        "id": "sku_runner_k_01",
        "title": "Nightlap Black Runners",
        "brand": "Aerolift",
        "color": "black",
        "category": "running-shoes",
        "price_cents": 13900,
        "currency": "USD",
        "description": "Black daily trainer, knit upper, foam midsole.",
        "image_url": None,
        "source_merchant": "walmart",
        "product_url": "https://walmart.com/example/sku_runner_k_01",
    },
    {
        "id": "sku_runner_w_03",
        "title": "Glaciermile White Trail",
        "brand": "Northhaul",
        "color": "white",
        "category": "trail-shoes",
        "price_cents": 17500,
        "currency": "USD",
        "description": "White trail runner, aggressive lugs, GORE-TEX.",
        "image_url": None,
        "source_merchant": "wayfair",
        "product_url": "https://wayfair.com/example/sku_runner_w_03",
    },
    {
        "id": "sku_tee_w_01",
        "title": "Stride Tech Tee (White)",
        "brand": "Aerolift",
        "color": "white",
        "category": "apparel",
        "price_cents": 3500,
        "currency": "USD",
        "description": "Moisture-wicking running tee.",
        "image_url": None,
        "source_merchant": "etsy",
        "product_url": "https://etsy.com/example/sku_tee_w_01",
    },
]


def _mock_search(
    query: str,
    from_cents: int,
    to_cents: int,
    merchants: tuple[str, ...],
) -> list[dict]:
    q = (query or "").lower().strip()
    out: list[dict] = []
    for p in _MOCK_PRODUCTS:
        if q and q not in p["title"].lower() and q not in p["category"].lower():
            continue
        if p["price_cents"] < from_cents or p["price_cents"] > to_cents:
            continue
        if merchants and p["source_merchant"] not in merchants:
            continue
        out.append(p)
    return out


def _serpapi_search(
    query: str,
    from_cents: int,
    to_cents: int,
    merchants: tuple[str, ...],
    api_key: str | None,
) -> list[dict]:
    return serpapi_client.search(query, from_cents, to_cents, merchants, api_key=api_key)


# ------------------------- public api -------------------------


def get_mode() -> str:
    return os.environ.get("UCP_CATALOG_MODE", "mock").lower().strip()


def search(
    query: str,
    from_cents: int,
    to_cents: int,
    allowed_merchants: list[str] | tuple[str, ...] | None,
    serpapi_key: str | None = None,
) -> list[dict]:
    """Search the active catalog for products matching the intent constraints.

    `serpapi_key` is only consulted in serpapi mode; if None, the server's
    SERPAPI_KEY env var is used.
    """
    merchants_t = tuple(sorted(set(allowed_merchants))) if allowed_merchants else ()
    if get_mode() == "serpapi":
        return _serpapi_search(query, from_cents, to_cents, merchants_t, serpapi_key)
    return _mock_search(query, from_cents, to_cents, merchants_t)


def get(product_id: str) -> dict | None:
    """Look up a product by id across the active catalog."""
    if get_mode() == "serpapi":
        return serpapi_client.get_by_id(product_id)
    return next((p for p in _MOCK_PRODUCTS if p["id"] == product_id), None)


def make_line_item(product_id: str, qty: int) -> LineItem:
    p = get(product_id)
    if p is None:
        raise ValueError(f"unknown product_id: {product_id}")
    return LineItem(
        product_id=p["id"],
        title=p["title"],
        qty=qty,
        unit_price_cents=p["price_cents"],
        image_url=p.get("image_url"),
        source_merchant=p.get("source_merchant"),
        product_url=p.get("product_url"),
    )
