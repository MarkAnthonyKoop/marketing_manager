"""The reasoning engine: marketing_manager drives the `claude` CLI under the hood.

The chatbot doesn't hard-code intent parsing. It hands the user's message to a
Claude Code session (the `claude` CLI) primed with a marketing-manager system
prompt and told which toolkit CLIs it can run. Claude then plans and executes —
posting via social_publisher, scraping via the platform managers, scheduling via
this package — using its own Bash tool, and replies in prose. We just relay.

Continuity: the first turn opens a session (`--output-format json` returns a
`session_id`); later turns `--resume` it, so the conversation keeps context and
any tool state across the chat. `ask()` takes an injectable `runner` so tests
never spawn a real subprocess.
"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass

from social_publisher.registry import PLATFORMS

CLAUDE_BIN = os.environ.get("CLAUDE_BIN", os.path.expanduser("~/.local/bin/claude"))
WORKSPACE = os.path.expanduser("~/claude")


def _tool_catalog() -> str:
    lines = []
    for p in PLATFORMS:
        lines.append(f"  - {p.key:10} ({p.status}): python3 -m {p.module} "
                     f"post|… — {p.label}, ≤{p.max_chars or '∞'} chars, media={p.media}")
    return "\n".join(lines)


SYSTEM_PROMPT = f"""You are Mark Nadon's marketing manager, operating his ~/claude social toolkit.
Identity for all attribution: Mark Nadon / MiddleMatter Music.

You accomplish requests by running these CLIs with Bash (always prefix with
`PYTHONPATH={WORKSPACE}` and use `python3`):

PUBLISH (fan out one post to many platforms at once):
  python3 -m social_publisher platforms            # list platforms + status
  python3 -m social_publisher post --to <keys|all|working> --text "..." [--link U] [--media P] [--dry-run]

PER-PLATFORM (posting + reading/scraping):
{_tool_catalog()}
  Read commands vary: bluesky/mastodon/reddit/x expose `search`; bluesky `feed`,
  mastodon `timeline`/`account`, reddit `subreddit`/`user`. Add `--json` for data.

SCHEDULE & DRIP CAMPAIGNS (this package):
  python3 -m marketing_manager schedule add --at <ISO> --to <keys> --text "..."
  python3 -m marketing_manager campaign tick      # release any due drip steps
  python3 -m marketing_manager history --tail 20

Rules of engagement:
- ALWAYS `--dry-run` first and show the user what would post; only post for real
  after they confirm, OR when they've clearly said "post it now".
- Gated platforms (linkedin, meta/facebook/instagram/threads, x, tiktok, rumble)
  will report `skip: no creds` until Mark sets their env vars — say so plainly,
  point to that manager's research.md, don't pretend it posted.
- Tailor copy per platform when limits matter (x=280). Be concise and concrete.
- You may read the managers' README/research.md files for specifics.
"""


@dataclass
class Reply:
    text: str
    session_id: str | None


def _default_runner(argv: list[str], timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                          cwd=WORKSPACE)


def ask(message: str, session_id: str | None = None, model: str | None = None,
        timeout: int = 600, runner=_default_runner) -> Reply:
    """Send one turn to the claude-backed brain. Returns its reply + session_id.

    First turn (session_id is None) injects the marketing system prompt and opens
    a session; later turns resume it for continuity.
    """
    argv = [CLAUDE_BIN, "-p", "--output-format", "json",
            "--permission-mode", "bypassPermissions"]
    if model:
        argv += ["--model", model]
    if session_id:
        argv += ["--resume", session_id]
    else:
        argv += ["--append-system-prompt", SYSTEM_PROMPT]
    argv += [message]

    proc = runner(argv, timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"claude exited {proc.returncode}: "
                           f"{(proc.stderr or proc.stdout or '').strip()[:300]}")
    return _parse(proc.stdout, session_id)


def _parse(stdout: str, prev_session: str | None) -> Reply:
    """Pull {result, session_id} from claude's --output-format json envelope."""
    stdout = stdout.strip()
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        # Fallback: treat raw stdout as the reply (e.g. text output format).
        return Reply(text=stdout, session_id=prev_session)
    text = data.get("result") or data.get("text") or ""
    return Reply(text=text, session_id=data.get("session_id") or prev_session)
