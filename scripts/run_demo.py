"""Launch the full demo: merchant (:8001) + PSP (:8002) + Streamlit (:8501).

Usage:
    uv run python scripts/run_demo.py

Ctrl-C to stop all three.
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

PROCESSES: list[subprocess.Popen] = []


def wait_for(url: str, timeout: float = 20.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = httpx.get(url, timeout=1.0)
            if r.status_code == 200:
                return
        except Exception:
            pass
        time.sleep(0.3)
    raise RuntimeError(f"timed out waiting for {url}")


def spawn(args: list[str], label: str) -> subprocess.Popen:
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    print(f"  starting {label}: {' '.join(args)}")
    proc = subprocess.Popen(args, cwd=ROOT, creationflags=creationflags)
    PROCESSES.append(proc)
    return proc


def stop_all() -> None:
    for proc in PROCESSES:
        if proc.poll() is not None:
            continue
        try:
            if os.name == "nt":
                proc.send_signal(signal.CTRL_BREAK_EVENT)  # type: ignore[attr-defined]
            else:
                proc.terminate()
        except Exception:
            pass
    for proc in PROCESSES:
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def main() -> None:
    # Clean event log so the UI starts fresh.
    sys.path.insert(0, str(ROOT))
    # Load .env (if present) so spawned subprocesses inherit SERPAPI_KEY etc.
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass
    from services.shared.eventlog import reset

    reset()

    py = sys.executable
    spawn(
        [py, "-m", "uvicorn", "services.merchant.main:app", "--port", "8001", "--log-level", "warning"],
        "merchant",
    )
    # PSP is not part of the 2nd PoC (stops at cart review). It can be started
    # manually for 1st-PoC regression tests, but we omit it from the demo launcher.
    try:
        wait_for("http://127.0.0.1:8001/healthz")
        print("  merchant ready (catalog mode = " + os.environ.get("UCP_CATALOG_MODE", "mock") + ").")
    except Exception as e:
        print(f"FAILED: {e}")
        stop_all()
        sys.exit(1)

    print("\n  starting Streamlit UI on http://localhost:8501\n")
    streamlit = spawn(
        [
            py,
            "-m",
            "streamlit",
            "run",
            str(ROOT / "ui" / "app.py"),
            "--server.headless",
            "true",
            "--server.port",
            "8501",
            "--browser.gatherUsageStats",
            "false",
        ],
        "streamlit",
    )

    try:
        streamlit.wait()
    except KeyboardInterrupt:
        print("\n  shutting down…")
    finally:
        stop_all()


if __name__ == "__main__":
    main()
