"""Minimal claude-agent-sdk sanity check.

Sends a one-shot prompt with NO tools and prints every message so we can see
whether the CLI is authenticated and reachable.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    SystemMessage,
    TextBlock,
    UserMessage,
    query,
)


async def main() -> None:
    options = ClaudeAgentOptions(
        system_prompt="You are a test. Reply with exactly: PONG",
        max_turns=1,
    )
    print("calling claude…")
    try:
        async for msg in query(prompt="ping", options=options):
            print(f"  msg type={type(msg).__name__}")
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        print(f"    text: {block.text!r}")
            elif isinstance(msg, ResultMessage):
                print(f"    is_error={getattr(msg, 'is_error', '?')} subtype={getattr(msg, 'subtype', '?')}")
                print(f"    full: {msg}")
    except Exception as e:
        print(f"  EXCEPTION: {type(e).__name__}: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
