# CLAUDE.md — marketing_manager

Agent-only notes. Read `README.md` first (esp. §3 architecture). Universal rules: `~/CLAUDE.md`.
This is the **top** of the marketing stack: it composes `social_publisher` + the `*_manager`
packages; nothing depends back on it.

## What lives here vs a sibling
- **Posting logic** belongs to `social_publisher` and the `*_manager` packages — never put a
  platform API call here. `publish.send` is the only send path and it just calls
  `social_publisher.fan_out` + logs history.
- **Reasoning** belongs to the `claude` brain, not a hard-coded intent parser. If you're tempted
  to add `if "post" in message:` dispatch, stop — extend `brain.SYSTEM_PROMPT` instead so Claude
  learns the new capability and composes the tools itself.
- **Web console** lives here now (Mark's call: build it into the `server.py` seam, not a separate
  package — it's Ren's remote control for *this* engine). It's three files: `server.py` (stdlib
  `http.server` transport + token auth + routing), `api.py` (pure handlers → engines), and
  `console.html` (the mobile SPA). Keep it stdlib-only — no Flask/web-framework dep.

## The web console (server.py / api.py / console.html)
- **Default-deny auth.** `server.make_server` raises unless `MARKETING_CONSOLE_TOKEN` is set;
  every `/api/*` request must send it in `X-Console-Token` (`hmac.compare_digest`). Only `/` and
  `/healthz` are public. Never hardcode the token — it (and any platform creds) come from
  `credanger` (`credanger get MARKETING_CONSOLE_TOKEN`; the deploy sets it in the server env). See
  `~/claude/credanger/`.
- **Default-safe actions.** `api._dry()` makes broadcasts and ticks **dry-run unless the payload
  says `dry_run: false`**. A web button must never post to the world by accident — preserve this.
- **Thin transport, testable handlers.** All logic is in `api.py` as plain dict→dict functions
  (no HTTP), unit-tested directly; `server.py` only routes/auths/serializes. Don't put engine logic
  in `server.py`. New endpoint = an `api.py` function + one route line + a test.
- **`_ConsoleServer` overrides `server_bind`** to skip `socket.getfqdn()` (it did a ~35s reverse-DNS
  on this network). Don't revert that — startup must be instant.
- Deploy contract: `python3 -m marketing_manager server --port $PORT` (see `renway/deploy.json`).

## The brain calls `claude` under the hood — keep that wiring intact
`brain.ask` runs `claude -p --output-format json --append-system-prompt <role> --permission-mode
bypassPermissions`, parses `{result, session_id}`, and `--resume`s the session on later turns for
continuity. Don't switch to `--continue` (it's directory-scoped and races across chats) — the
explicit `session_id` is deterministic. `CLAUDE_BIN` overrides the binary path.

Heads-up when testing: invoking `marketing_manager chat` *from inside* a Claude Code session
nests claude-in-claude (slow/expensive, possible session confusion). Unit tests inject a fake
`runner`/`ask` and never spawn a real subprocess — keep it that way. For a real smoke, run it
from a plain terminal, not from within an agent.

## Engines are deterministic — preserve the injection seams
`schedule.tick`, `campaigns.tick_campaign/tick_all` take an injected `now` (a datetime) and a
`poster` callable. The CLI passes `timing.now()` + `publish.send`; tests pass a fixed time + a
recording fake. Never read the wall clock or call the network inside the engine core — that's
what makes "is this due / did it send once / does the campaign close" testable. New time math
goes through `timing.py` (one UTC ISO convention) so both engines agree.

Idempotency is load-bearing: a step/item flips to `sent` so a second `tick` in the same window
won't repost. Don't add logic that re-sends `sent` items. `--dry-run` must NOT mark sent.

## State
JSON under `MARKETING_MANAGER_HOME` (default `~/.local/share/marketing_manager/`):
`campaigns.json`, `schedule.json`, `history.jsonl`. `store.py` is dict-in/dict-out with
atomic-ish writes (tmp + rename). Tests set `MARKETING_MANAGER_HOME` to a tmp dir
(`conftest.py`) so they never touch real state — rely on that fixture.

## Reddit/video platforms in a generic broadcast
`--to all`/`working` includes platforms that need extra inputs (Reddit needs `--title` +
subreddit; YouTube/TikTok/Rumble need a video). Those managers **skip** (not fail) when the input
is absent, so a text-only broadcast stays quiet. If you change a manager to hard-fail on missing
input, a generic broadcast will show a spurious FAIL — prefer skip for "this content isn't
postable here." (For Meta, `social_publisher` exports `SOCIAL_PUBLISHER_PLATFORM` so the
instagram/threads rows hit the right surface — see `meta_manager.auth.default_surface`.)

## Run the tests
```bash
PYTHONPATH=~/claude python3 -m pytest ~/claude/marketing_manager/tests/ -q
```
All offline. A bug fix gets a regression test with a fixed `now` + fake poster.

## Smoke test
```bash
PYTHONPATH=~/claude python3 -m marketing_manager post --to working --text hi --dry-run   # all skip
PYTHONPATH=~/claude python3 -m marketing_manager campaign new --name T --to bluesky --step "0:hi"
PYTHONPATH=~/claude python3 -m marketing_manager campaign tick --dry-run
```

## Python: use the 3.14 venv
Run/test on `~/claude/.venv` (Python 3.14, has `requests`+`pytest`):
`PYTHONPATH=~/claude ~/claude/.venv/bin/python -m pytest ~/claude/marketing_manager/tests -q`.
Code still runs on the legacy `/usr/bin/python3` (3.9.6) too — keep `from __future__ import
annotations` at the top of every module — but new work targets the venv (see `~/claude/CLAUDE.md`).

## E2E UI suite (added 2026-07-30)
The onboarding dialog, guide rendering, XSS escaping, and the tick-button semantics live in
`console.html` where unit tests can't see them. `tests/e2e_console.py` (no `test_` prefix — 
excluded from the offline pytest run by design) drives the real page in headless Chrome via CDP:

```bash
PYTHONPATH=~/claude ~/claude/.venv/bin/python ~/claude/marketing_manager/tests/e2e_console.py
```

26 checks; needs Google Chrome, runs fully offline (local ephemeral server + temp state).
Run it after ANY console.html change. History lesson baked into it: the original
`tick(kind,send)` signature silently inverted the Tick (dry)/(send) buttons — a bug unit tests
could never catch because it lived in the onclick wiring. The E2E asserts dry-previews +
confirm-gated real sends; keep those assertions.

Rendering rule for the console: EVERY dynamic value goes through `esc()` before `innerHTML`
(campaign names, chat replies, scrape rows are attacker-influenceable). `md2html` escapes
before transforming — keep that order.

STRICT CSP (2026-07-30): the console is split into `console.html` + `console.js` +
`console.css` and the edge policy is `script-src 'self'; style-src 'self'` — NO inline
script, style blocks, on*= handlers, or style= attributes anywhere in the page
(`test_page_is_strict_csp_ready` enforces this; the E2E runs with the strict policy
ENFORCED and asserts injected inline script is browser-blocked). Wire new UI in
`console.js`'s `wire()` with addEventListener / element properties; new styling goes in
`console.css` classes (JS `.style` property assignment is fine — CSP doesn't gate CSSOM).
