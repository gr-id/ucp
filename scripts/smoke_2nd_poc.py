"""Smoke test for the 2nd PoC.

Verifies:
  1. `build_intent_from_form` produces a valid IntentMandate with a stub sig.
  2. Mock catalog mode honors allowed_merchants + price band.
  3. SerpAPI mode (if SERPAPI_KEY set) returns live products from the
     whitelisted merchants. Skipped with a notice otherwise.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Ensure Unicode (em-dash, Korean) prints cleanly on Windows consoles.
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Load .env if present, so SERPAPI_KEY / UCP_CATALOG_MODE pick up without
# needing the caller to export them manually.
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

from services.merchant import catalog, serpapi_client
from services.shared.intent import build_intent_from_form


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def test_intent_build() -> None:
    section("Intent build")
    form = {
        "item_query": "  running shoes  ",
        "price_from_cents": 5000,
        "price_to_cents": 15000,
        "allowed_merchants": ["walmart", "etsy"],
        "valid_hours": 24,
        "auto_purchase": False,
    }
    intent = build_intent_from_form(form)
    assert intent.item_query == "running shoes", intent.item_query
    assert intent.price_range.from_cents == 5000
    assert intent.price_range.to_cents == 15000
    assert intent.allowed_merchants == ["etsy", "walmart"]  # sorted
    assert intent.expires_at > int(time.time())
    assert intent.signature.signer == "user"
    assert len(intent.signature.payload_hash) == 16
    print(f"  ok — jti={intent.jti} expires_at={intent.expires_at} sig_hash={intent.signature.payload_hash}")


def test_mock_catalog() -> None:
    section("Mock catalog")
    os.environ["UCP_CATALOG_MODE"] = "mock"
    results = catalog.search(
        query="running",
        from_cents=10_000,
        to_cents=15_000,
        allowed_merchants=["walmart", "target"],
    )
    assert all(r["source_merchant"] in {"walmart", "target"} for r in results)
    assert all(10_000 <= r["price_cents"] <= 15_000 for r in results)
    for r in results:
        print(f"  {r['source_merchant']:>8}  {r['title']:<30}  ${r['price_cents']/100:.2f}")
    assert len(results) >= 1, "mock catalog should yield at least one hit"
    print(f"  ok — {len(results)} hit(s)")


def test_serpapi_catalog() -> None:
    section("SerpAPI catalog (live)")
    if not os.environ.get("SERPAPI_KEY"):
        print("  SKIPPED — set SERPAPI_KEY to run live test")
        return
    os.environ["UCP_CATALOG_MODE"] = "serpapi"
    results = catalog.search(
        query="running shoes white",
        from_cents=5_000,
        to_cents=20_000,
        allowed_merchants=["walmart", "target", "wayfair", "etsy"],
    )
    if not results:
        print("  no results returned (Google Shopping may have no whitelisted-merchant matches for this query)")
        return
    seen_merchants = {r["source_merchant"] for r in results}
    assert seen_merchants.issubset({"walmart", "target", "wayfair", "etsy"})
    for r in results[:5]:
        print(f"  {r['source_merchant']:>8}  {r['title'][:40]:<40}  ${r['price_cents']/100:.2f}")
    print(f"  ok — {len(results)} hit(s) across merchants {sorted(seen_merchants)}")
    print(f"  cache_stats: {serpapi_client.cache_stats()}")


def main() -> None:
    test_intent_build()
    test_mock_catalog()
    test_serpapi_catalog()
    print("\nAll smoke tests passed (with SerpAPI step possibly skipped).")


if __name__ == "__main__":
    main()
