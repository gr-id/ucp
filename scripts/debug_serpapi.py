"""Test: can we use google_shopping with merchant name in query for all four?"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

import httpx

api_key = os.environ.get("SERPAPI_KEY")
assert api_key, "SERPAPI_KEY missing"

# Try a variety of queries that should land in each merchant.
tests = [
    ("walmart", "running shoes"),
    ("target", "running shoes"),
    ("wayfair", "office chair"),
    ("etsy", "handmade ring"),
]

for merchant, query in tests:
    q = f"{query} {merchant}"
    print(f"\n=== q={q!r} ===")
    with httpx.Client(timeout=15) as client:
        r = client.get(
            "https://serpapi.com/search.json",
            params={
                "engine": "google_shopping",
                "q": q,
                "gl": "us",
                "hl": "en",
                "api_key": api_key,
            },
        )
        data = r.json()
    if "error" in data:
        print(f"  error: {data['error']}")
        continue
    results = data.get("shopping_results") or []
    print(f"  total: {len(results)}")
    matched = [s for s in results if (s.get("source", "")).lower().replace(".com","").startswith(merchant)]
    print(f"  matched merchant={merchant}: {len(matched)}")
    for i, s in enumerate(matched[:3]):
        print(f"    [{i}] source={s.get('source')!r}")
        print(f"        title={(s.get('title') or '')[:60]!r}")
        print(f"        price={s.get('price')!r}  extracted={s.get('extracted_price')!r}")
        print(f"        thumbnail={s.get('thumbnail','')[:60]!r}")
