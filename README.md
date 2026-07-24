# marketing_manager

Your **AI marketing manager** — a chatbot that actually runs your social toolkit. Talk to it in
plain English ("draft a launch thread and dry-run it everywhere", "set up a 5-touch drip for the
album", "what's getting traction on Bluesky this week?") and it plans + executes by driving
`social_publisher` and the per-platform `*_manager` packages. The reasoning engine is **Claude
Code itself** (the `claude` CLI), invoked under the hood; this package gives it a marketing role,
a tool catalog, and the scheduling/campaign/history machinery a marketing manager needs.

Status: **working** (REPL + engines), v0.1.0, tested 2026-06-19 (22 unit tests pass, offline).
Web UI is a documented seam (`server.py`), not built yet — REPL is the current front-end.

---

## 1. User manual

### Install
```bash
~/claude/marketing_manager/install.sh        # pure stdlib; needs the toolkit siblings on PYTHONPATH
```
Runtime needs: `social_publisher` + the `*_manager` packages importable/spawnable, and the
`claude` CLI at `~/.local/bin/claude` (override with `CLAUDE_BIN`). Run with `PYTHONPATH=~/claude`.

### Talk to it (the headline)
```bash
python3 -m marketing_manager chat
```
```
you › draft a punchy launch post for our new single and dry-run it to all working platforms
mgr › Here's the copy I'd post … [runs social_publisher --dry-run, shows the per-platform table]
      Want me to post it for real to bluesky + mastodon?
you › yes, and schedule a reminder for friday 9am
mgr › Posted ✅ (bluesky, mastodon). Scheduled a reminder for 2026-06-26T13:00Z. …
```
The brain dry-runs and confirms before posting for real, tailors copy to platform limits, and
tells you plainly when a gated platform needs credentials.

One-shot (no REPL): `python3 -m marketing_manager ask "what platforms can I post to right now?"`

### Do things directly (no chatbot)
```bash
# Broadcast now (logged to history)
python3 -m marketing_manager post --to bluesky,mastodon --text "Out now!" --link https://… --dry-run

# Content calendar
python3 -m marketing_manager schedule add --at 2026-06-26T13:00:00Z --to working --text "Reminder: single out now"
python3 -m marketing_manager schedule list
python3 -m marketing_manager schedule tick           # send anything now due (cron this)

# Drip campaign (release a sequence over days)
python3 -m marketing_manager campaign new --name "Album Rollout" --to bluesky,mastodon \
    --step "0:Teaser drop 👀" --step "2:Single out now →" --step "7:Full album live 🎸"
python3 -m marketing_manager campaign tick           # release due steps (cron this)
python3 -m marketing_manager campaign list

# Monitor
python3 -m marketing_manager scrape bluesky "MiddleMatter"
python3 -m marketing_manager history --tail 20
```

### Run the web console (phone/tablet remote control)
A mobile-first console (built into `server.py`) for driving the engine without a terminal —
compose & broadcast, drip campaigns, schedule, and monitor:
```bash
export MARKETING_CONSOLE_TOKEN="a-long-random-secret"   # required; server is default-deny
PYTHONPATH=~/claude ~/claude/.venv/bin/python -m marketing_manager server --port 8765
# open http://127.0.0.1:8765 on a phone/tablet, enter the token to unlock
```
Every `/api/*` call needs the token (`X-Console-Token` header); broadcasts/ticks **preview
(dry-run) by default** and only post for real when you untick Dry-run. This is the surface Ren
drives remotely — see `~/claude/renway/`.

### Automate releases
`schedule tick` and `campaign tick` are idempotent — wire them to cron (or the `/schedule`
routine) to release due content unattended:
```cron
*/15 * * * * PYTHONPATH=~/claude python3 -m marketing_manager schedule tick
*/15 * * * * PYTHONPATH=~/claude python3 -m marketing_manager campaign tick
```

---

## 2. Reference

`python3 -m marketing_manager [--model opus|sonnet] <subcommand>`

| Command | Does |
| --- | --- |
| `chat` | interactive AI marketing-manager REPL (claude-backed) |
| `ask "msg"` | one-shot question to the brain |
| `post --to --text [--link --media --title --tag --dry-run]` | broadcast now (logged) |
| `schedule {add\|list\|tick\|rm}` | one-off content calendar (`add` needs `--at` ISO, `--to`, `--text`) |
| `campaign {new\|list\|show\|tick\|pause\|resume}` | drip sequences |
| `scrape PLATFORM QUERY [--limit]` | search/monitor a platform |
| `history [--tail N]` | what was sent, with per-platform outcome |
| `server [--host --port]` | run the mobile web console (needs `MARKETING_CONSOLE_TOKEN`) |

`--to` accepts a comma list, or `all` / `working`. Campaign steps: `--step "DAYS:TEXT"`
(repeatable) or `--from-json FILE` (a list of `{offset_days, offset_hours, text, link, media,
title, tags}` step dicts). State lives under `MARKETING_MANAGER_HOME`
(default `~/.local/share/marketing_manager/`).

### Python API
```python
from marketing_manager import brain, campaigns, schedule, publish, timing
brain.ask("draft a post and dry-run it to working platforms")          # -> Reply(text, session_id)
campaigns.create("Launch", ["bluesky"], timing.to_iso(timing.now()),
                 steps=[{"offset_days": 0, "text": "day 0"}])
campaigns.tick_all(timing.now())                                       # release due steps
```

---

## 3. Architecture

```
marketing_manager/
├── brain.py       drives the `claude` CLI: marketing system prompt + tool catalog,
│                  --output-format json, --resume for conversation continuity
├── chat.py        the terminal REPL loop over brain.ask (single-shot `once` too)
├── publish.py     the one send path → social_publisher.fan_out + history logging
├── schedule.py    content calendar: add / due / tick (one-off posts)
├── campaigns.py   drip engine: create / due_steps / tick (multi-step sequences)
├── scrape.py      forward to each manager's read commands; never dies on one platform
├── timing.py      one UTC ISO convention; injected `now` keeps engines deterministic
├── store.py       JSON persistence (campaigns / schedule / history)
├── api.py         web console handlers (pure dict→dict over the engines; testable)
├── server.py      web console: stdlib http.server + token auth + routing → api.py
├── console.html   the mobile-first single-page console UI (vanilla JS)
└── __main__.py    CLI wiring all of the above
```

**Theory of operation.** Posting is unified by `social_publisher` (one Post → many platforms,
concurrently). `marketing_manager` sits on top and adds the three things a manager does that a
publisher doesn't: **decide what to say** (the claude brain), **decide when** (schedule +
campaigns), and **remember what happened** (history). The brain doesn't hard-code intent parsing
— it's a full Claude Code session primed with a marketing role and told which toolkit CLIs to
run, so its capabilities grow automatically as you add platform managers.

**Why claude-under-the-hood instead of a rules engine:** marketing asks are open-ended (draft,
tailor per platform, judge timing, summarize engagement). A Claude Code session with Bash access
to the toolkit handles all of that and composes the tools in ways a fixed command tree can't.
`brain.ask` keeps a `session_id` so the conversation has memory across turns.

**Determinism where it counts:** the schedule/campaign engines take an injected `now` and
`poster`, so "is this step due / did it send" is unit-tested without a clock or network. Only the
CLI reads the real clock and the real publisher.

**Dependency direction:** `marketing_manager` → `social_publisher` (publish) and → the platform
manager CLIs + the `claude` binary (subprocess). Nothing depends back on it. It's the top of the
stack.

---

## 4. Next steps

1. **Web console — built** (2026-06-25). `server.py` + `api.py` + `console.html`: a mobile-first,
   token-auth'd SPA (compose/broadcast, campaigns, schedule, monitor, chat) on stdlib
   `http.server`. Run with `… -m marketing_manager server`. Tested locally (HTTP + auth + engine
   wiring); deployment lives in `~/claude/renway/` + `~/claude/remote_server/`. Next here: a
   per-platform "confirm to send" affordance richer than the dry-run toggle, and image upload in
   Compose (needs the media-hosting item below for IG/Threads).
2. **Media hosting** — Instagram/Threads need publicly-hosted media URLs (see `meta_manager`).
   Add a small uploader (e.g. to a bucket) so image/video campaigns work end-to-end on Meta.
3. **Engagement digest** — a `digest` command that sweeps `scrape` across platforms and has the
   brain summarize mentions/traction into a daily report.
4. **Best-time scheduling** — let the brain suggest send times from `history` + per-platform
   engagement instead of fixed offsets.
5. **Approval queue** — a `--require-approval` mode where scheduled/drip sends post to a review
   list the brain surfaces in chat before they go live.
6. **Per-platform overrides in campaigns** — thread `Post.overrides` through campaign steps so one
   step carries platform-native copy (x ≤280, long-form on LinkedIn) in a single definition.
