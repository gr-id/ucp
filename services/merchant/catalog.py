"""Hardcoded UCP catalog for the demo."""

from __future__ import annotations

from services.shared.mandates import LineItem

PRODUCTS: list[dict] = [
    {
        "id": "sku_runner_w_01",
        "title": "Cloudstride White Runners",
        "brand": "Aerolift",
        "color": "white",
        "category": "running-shoes",
        "price_cents": 12900,
        "currency": "USD",
        "description": "Lightweight white running shoes with breathable mesh upper.",
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
    },
]


def search(query: str | None, max_price_cents: int | None, color: str | None) -> list[dict]:
    """Substring search over title/category (not description), plus filters."""
    q = (query or "").lower().strip()
    out = []
    for p in PRODUCTS:
        if q and q not in p["title"].lower() and q not in p["category"].lower():
            continue
        if max_price_cents is not None and p["price_cents"] > max_price_cents:
            continue
        if color and p["color"].lower() != color.lower():
            continue
        out.append(p)
    return out


def get(product_id: str) -> dict | None:
    return next((p for p in PRODUCTS if p["id"] == product_id), None)


def make_line_item(product_id: str, qty: int) -> LineItem:
    p = get(product_id)
    if p is None:
        raise ValueError(f"unknown product_id: {product_id}")
    return LineItem(
        product_id=p["id"],
        title=p["title"],
        qty=qty,
        unit_price_cents=p["price_cents"],
    )
