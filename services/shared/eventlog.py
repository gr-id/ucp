"""In-process event log shared between agent/merchant/PSP for UI inspection.

The Streamlit UI tails ./logs/events.jsonl for the protocol inspector pane.
Services append-only; UI reads in a polling loop.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Literal

LOGS_DIR = Path(__file__).resolve().parent.parent.parent / "logs"
LOGS_DIR.mkdir(exist_ok=True)
EVENT_FILE = LOGS_DIR / "events.jsonl"

_LOCK = threading.Lock()

Actor = Literal["user", "agent", "merchant", "psp"]


def log_event(
    actor: Actor,
    kind: str,
    summary: str,
    detail: dict[str, Any] | None = None,
) -> None:
    """Append a single protocol event. Safe to call from any service."""
    event = {
        "ts": time.time(),
        "actor": actor,
        "kind": kind,
        "summary": summary,
        "detail": detail or {},
    }
    with _LOCK:
        with EVENT_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")


def reset() -> None:
    """Clear the event log — called at the start of each demo session."""
    with _LOCK:
        EVENT_FILE.write_text("", encoding="utf-8")


def read_all() -> list[dict[str, Any]]:
    if not EVENT_FILE.exists():
        return []
    with EVENT_FILE.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]
