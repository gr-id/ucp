"""Static merchant-reputation registry (3rd PoC).

The UCP-live merchants (Walmart, Target, Wayfair, Etsy) don't publish a
machine-readable trust score. SerpAPI also doesn't expose one. To make the
comparison engine useful in a demo without faking real-world data, we ship a
small, hand-curated registry here and surface its source explicitly to the UI
and the Protocol Inspector (`source=static_demo_registry`).

If the comparison engine ever runs against a merchant outside this list
(e.g. the SerpAPI source field returns something unexpected) it falls back
to `DEFAULT_REPUTATION` and tags the dimension as defaulted in
`ComparisonReport.dimensions_used`.

DO NOT treat these numbers as authoritative. They exist purely so the demo
can show how a priority weighting changes outcomes when reputation matters.
"""

from __future__ import annotations

# 0..100. Numbers are placeholders, not benchmarks. Chosen so the demo
# produces visibly different winners across presets without any one merchant
# dominating every dimension.
_REPUTATION: dict[str, dict[str, object]] = {
    "walmart": {
        "score": 78,
        "note": "Large marketplace, fast shipping network, mixed seller quality.",
    },
    "target": {
        "score": 92,
        "note": "First-party retail, consistent return policy, slightly higher prices.",
    },
    "wayfair": {
        "score": 72,
        "note": "Strong home-goods catalog; longer shipping times and pricier returns.",
    },
    "etsy": {
        "score": 66,
        "note": "Independent sellers, high variance in fulfillment speed and quality.",
    },
}

DEFAULT_REPUTATION = 60
SOURCE_TAG = "static_demo_registry"


# Deterministic shipping descriptors per merchant. The number is a rough
# delivery-time signal mapped to a 0..1 score used inside Comparison Engine.
# Lower days_eta = higher shipping score.
_SHIPPING: dict[str, dict[str, object]] = {
    "walmart": {"days_eta": 2, "note": "Walmart+ 2-day shipping on most SKUs."},
    "target":  {"days_eta": 3, "note": "Target RedCard 2-3 day shipping."},
    "wayfair": {"days_eta": 6, "note": "Wayfair standard 5-7 days (bulky items longer)."},
    "etsy":    {"days_eta": 7, "note": "Etsy: depends on seller, typically 5-10 days."},
}

DEFAULT_SHIPPING_DAYS = 7
DEFAULT_SHIPPING_NOTE = "Shipping ETA unknown; defaulting to 7 days."


def reputation_score(merchant: str) -> int:
    entry = _REPUTATION.get(merchant)
    if entry is None:
        return DEFAULT_REPUTATION
    return int(entry["score"])


def reputation_note(merchant: str) -> str:
    entry = _REPUTATION.get(merchant)
    if entry is None:
        return "Unknown merchant; defaulted reputation score."
    return str(entry["note"])


def shipping_days(merchant: str) -> int:
    entry = _SHIPPING.get(merchant)
    if entry is None:
        return DEFAULT_SHIPPING_DAYS
    return int(entry["days_eta"])


def shipping_note(merchant: str) -> str:
    entry = _SHIPPING.get(merchant)
    if entry is None:
        return DEFAULT_SHIPPING_NOTE
    return str(entry["note"])


def is_registered(merchant: str) -> bool:
    return merchant in _REPUTATION
