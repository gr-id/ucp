"""End-to-end smoke test for the 2nd PoC.

Starts the merchant service, runs the form-driven mock agent, and verifies
that the cart is created (the PoC stops there — no PSP step). PSP is still
started for backward compatibility but is not exercised by this test.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# .env so SERPAPI_KEY / UCP_CATALOG_MODE work without manual export.
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass


def wait_for(url: str, timeout: float = 15.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = httpx.get(url, timeout=1.0)
            if r.status_code == 200:
                return
        except Exception:
            pass
        time.sleep(0.25)
    raise RuntimeError(f"timed out waiting for {url}")


def start_uvicorn(module: str, port: int) -> subprocess.Popen:
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    return subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn", module,
            "--host", "127.0.0.1", "--port", str(port),
            "--log-level", "warning",
        ],
        cwd=ROOT,
        creationflags=creationflags,
    )


def stop(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if os.name == "nt":
        proc.send_signal(signal.CTRL_BREAK_EVENT)  # type: ignore[attr-defined]
    else:
        proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def main() -> None:
    from services.shared.eventlog import read_all, reset

    # Force mock mode so the e2e doesn't depend on SerpAPI being available.
    os.environ["UCP_CATALOG_MODE"] = "mock"

    reset()
    merchant = start_uvicorn("services.merchant.main:app", 8001)
    try:
        wait_for("http://127.0.0.1:8001/healthz")
        print("merchant up (mock catalog).")

        from agent.mock_agent import run_until_cart_form

        form = {
            "item_query": "running",
            "price_from_cents": 5_000,
            "price_to_cents": 15_000,
            "allowed_merchants": ["walmart", "target", "wayfair", "etsy"],
            "valid_hours": 24,
            "auto_purchase": False,
            "buyer_email": "demo@example.com",
        }
        session = run_until_cart_form(form)

        assert session.intent is not None, "intent must be built"
        assert session.intent.signature.signer == "user"
        assert session.error is None, f"unexpected error: {session.error}"
        assert session.selected is not None, "expected a selected product"
        assert session.checkout_body is not None, "expected a cart"
        assert session.merchant_authorization is not None, "expected merchant signature"
        assert session.merchant_authorization["signature"]["signer"] == "merchant"

        cart = session.checkout_body
        print(f"cart: {cart['line_items'][0]['title']} "
              f"from {cart['line_items'][0]['source_merchant']} "
              f"= ${cart['total_cents']/100:.2f}")
        print(f"merchant_authorization stub: {session.merchant_authorization['signature']}")

        # Negative case: price band that excludes everything → empty result.
        narrow_form = {**form, "price_from_cents": 1, "price_to_cents": 50}
        narrow_session = run_until_cart_form(narrow_form)
        assert narrow_session.selected is None, "narrow band should yield no selection"
        print("narrow-band negative case: no selection (as expected)")

        # Negative case: single merchant that won't match query 'running'.
        # (We pick wayfair: only the white-trail shoe lives there.)
        wayfair_form = {**form, "allowed_merchants": ["wayfair"], "price_from_cents": 0, "price_to_cents": 10_000}
        wayfair_session = run_until_cart_form(wayfair_form)
        assert wayfair_session.selected is None, "wayfair below $100 should yield no selection"
        print("wayfair-only narrow-band: no selection (as expected)")

        print("\n--- event log ---")
        for ev in read_all():
            print(f"  [{ev['actor']}] {ev['kind']}: {ev['summary']}")
    finally:
        stop(merchant)


if __name__ == "__main__":
    main()
