"""End-to-end smoke test: start merchant + PSP, run the mock agent, print event log."""

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
            sys.executable,
            "-m",
            "uvicorn",
            module,
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
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

    reset()
    merchant = start_uvicorn("services.merchant.main:app", 8001)
    psp = start_uvicorn("services.psp.main:app", 8002)
    try:
        wait_for("http://127.0.0.1:8001/healthz")
        wait_for("http://127.0.0.1:8002/healthz")
        print("services up.")

        from agent.mock_agent import finalize, run_until_cart

        session = run_until_cart("Find me white running shoes under $150 and buy them.")
        assert session.checkout_body is not None, "expected a cart"
        print(f"cart: {session.checkout_body['line_items'][0]['title']} = ${session.checkout_body['total_cents']/100:.2f}")
        finalize(session)
        assert session.psp_result is not None
        print(f"charged: {session.psp_result['transaction_id']} (${session.psp_result['amount_cents']/100:.2f})")

        print("\n--- event log ---")
        for ev in read_all():
            print(f"  [{ev['actor']}] {ev['kind']}: {ev['summary']}")
    finally:
        stop(merchant)
        stop(psp)


if __name__ == "__main__":
    main()
