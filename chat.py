"""The interactive REPL: a marketing-manager chatbot in your terminal.

A thin loop over `brain.ask` — read a line, send it to the claude-backed brain
(which runs the toolkit to do the work), print the reply, keep the session id so
the next turn has context. All the intelligence lives in the brain + the tools;
this file just handles the terminal.

Run it: `python3 -m marketing_manager chat`. Type 'exit' (or Ctrl-D) to quit.
"""
from __future__ import annotations

import sys

from . import brain

BANNER = """marketing_manager — your AI marketing manager (powered by Claude Code)
Identity: Mark Nadon / MiddleMatter Music
Ask me to draft + post across platforms, schedule content, run drip campaigns,
or scrape/monitor. I dry-run first and confirm before posting for real.
Type 'exit' or Ctrl-D to quit.
"""


def repl(model: str | None = None, ask=brain.ask) -> int:
    """Run the chat loop. `ask` is injectable for testing."""
    print(BANNER)
    session_id: str | None = None
    while True:
        try:
            message = input("\nyou › ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nbye 👋")
            return 0
        if not message:
            continue
        if message.lower() in {"exit", "quit", ":q"}:
            print("bye 👋")
            return 0
        try:
            reply = ask(message, session_id=session_id, model=model)
        except Exception as e:  # noqa: BLE001 — keep the REPL alive on a bad turn
            print(f"[error] {type(e).__name__}: {e}", file=sys.stderr)
            continue
        session_id = reply.session_id
        print(f"\nmgr › {reply.text}")


def once(message: str, model: str | None = None, ask=brain.ask) -> str:
    """Single-shot: one message in, the reply text out. For scripting/`ask` CLI."""
    return ask(message, model=model).text
