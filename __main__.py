"""marketing_manager CLI. `python3 -m marketing_manager <subcommand>`.

    chat                      interactive AI marketing-manager REPL (the headline)
    ask "..."                 one-shot question to the brain
    post --to --text          broadcast now (logged to history)
    schedule {add|list|tick|rm}   content calendar of one-off posts
    campaign {new|list|show|tick|pause|resume}   drip sequences
    scrape PLATFORM QUERY     search a platform (monitoring)
    history [--tail N]        what was sent
    server [--host --port]    run Ren's mobile web console (token-auth'd)
"""
from __future__ import annotations

import argparse
import json
import sys

from social_publisher import Post, all_keys, working_keys

from . import campaigns, chat, publish, scrape, schedule, store, timing


def _targets(raw: str) -> list[str]:
    raw = raw.strip().lower()
    if raw == "all":
        return all_keys()
    if raw == "working":
        return working_keys()
    return [t.strip() for t in raw.split(",") if t.strip()]


def _cmd_chat(a):
    return chat.repl(model=a.model)


def _cmd_ask(a):
    print(chat.once(a.message, model=a.model))
    return 0


def _cmd_post(a):
    post = Post(text=a.text, media=a.media or [], link=a.link, title=a.title,
                tags=a.tag or [])
    results = publish.send(post, _targets(a.to), timing.to_iso(timing.now()),
                           "manual", dry_run=a.dry_run)
    for r in results:
        mark = "skip" if r.skipped else (" ok " if r.ok else "FAIL")
        print(f"[{mark}] {r.platform:12} {r.url or r.error or r.id or ''}")
    print("·", publish.summarize(results))
    return 0 if all(r.ok for r in results) else 1


def _cmd_schedule(a):
    if a.action == "add":
        item = schedule.add(a.at, _targets(a.to), a.text, media=a.media or [],
                            link=a.link, title=a.title, tags=a.tag or [])
        print(f"scheduled {item['id']} for {item['at']} → {','.join(item['platforms'])}")
    elif a.action == "list":
        for i in store.load_schedule():
            print(f"{i['status']:7} {i['at']}  {i['id']:30} {i['text'][:50]!r}")
    elif a.action == "tick":
        acted = schedule.tick(timing.now(), dry_run=a.dry_run)
        print(f"sent {len(acted)} due item(s)" if acted else "nothing due")
        for i in acted:
            print(f"  {i['id']}: {i.get('summary')}")
    elif a.action == "rm":
        print("removed" if schedule.remove(a.id) else "not found")
    return 0


def _cmd_campaign(a):
    if a.action == "new":
        steps = _steps_from_args(a)
        c = campaigns.create(a.name, _targets(a.to), a.start, steps)
        print(f"created campaign {c['id']} with {len(c['steps'])} steps")
    elif a.action == "list":
        for c in store.load_campaigns():
            sent = sum(1 for s in c["steps"] if s["status"] == "sent")
            print(f"{c['status']:7} {c['id']:24} {sent}/{len(c['steps'])} sent  {c['name']!r}")
    elif a.action == "show":
        print(json.dumps(store.get_campaign(a.id) or {"error": "not found"}, indent=2))
    elif a.action == "tick":
        out = campaigns.tick_all(timing.now(), dry_run=a.dry_run)
        print(json.dumps({k: len(v) for k, v in out.items()}, indent=2)
              if out else "nothing due")
    elif a.action in {"pause", "resume"}:
        status = "paused" if a.action == "pause" else "active"
        print("ok" if campaigns.set_status(a.id, status) else "not found")
    return 0


def _steps_from_args(a) -> list[dict]:
    if a.from_json:
        data = json.loads(open(a.from_json).read())
        return data if isinstance(data, list) else data.get("steps", [])
    steps = []
    for spec in (a.step or []):
        # "DAYS:TEXT"  (hours optional as DAYS:HOURS::TEXT not supported — keep simple)
        days, _, text = spec.partition(":")
        steps.append({"offset_days": float(days), "text": text})
    return steps


def _cmd_scrape(a):
    rows = scrape.search(a.platform, a.query, limit=a.limit)
    print(json.dumps(rows, indent=2))
    return 0 if isinstance(rows, list) else 1


def _cmd_server(a):
    from . import server
    try:
        server.serve(host=a.host, port=a.port)
    except RuntimeError as e:  # e.g. missing MARKETING_CONSOLE_TOKEN (default-deny)
        print(f"error: {e}", file=sys.stderr)
        return 2
    return 0


def _cmd_history(a):
    for e in store.read_history(limit=a.tail):
        s = publish.summarize([__import__("social_publisher").PostResult.from_dict(r)
                               for r in e.get("results", [])])
        print(f"{e['ts']}  {e['source']:24} {s}  {e['text'][:40]!r}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="marketing_manager")
    p.add_argument("--model", default=None, help="claude model alias (opus/sonnet/…)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("chat", help="interactive AI marketing-manager REPL").set_defaults(func=_cmd_chat)

    sp = sub.add_parser("ask", help="one-shot question to the brain")
    sp.add_argument("message")
    sp.set_defaults(func=_cmd_ask)

    sp = sub.add_parser("post", help="broadcast now")
    sp.add_argument("--to", required=True)
    sp.add_argument("--text", required=True)
    sp.add_argument("--media", action="append")
    sp.add_argument("--link"); sp.add_argument("--title")
    sp.add_argument("--tag", action="append")
    sp.add_argument("--dry-run", action="store_true")
    sp.set_defaults(func=_cmd_post)

    sp = sub.add_parser("schedule", help="content calendar")
    sp.add_argument("action", choices=["add", "list", "tick", "rm"])
    sp.add_argument("--at"); sp.add_argument("--to", default="working")
    sp.add_argument("--text"); sp.add_argument("--link"); sp.add_argument("--title")
    sp.add_argument("--media", action="append"); sp.add_argument("--tag", action="append")
    sp.add_argument("--id"); sp.add_argument("--dry-run", action="store_true")
    sp.set_defaults(func=_cmd_schedule)

    sp = sub.add_parser("campaign", help="drip sequences")
    sp.add_argument("action", choices=["new", "list", "show", "tick", "pause", "resume"])
    sp.add_argument("--name", default=""); sp.add_argument("--to", default="working")
    sp.add_argument("--start", default=None, help="anchor ISO time")
    sp.add_argument("--step", action="append", help="'DAYS:TEXT' (repeatable)")
    sp.add_argument("--from-json", default=None, help="steps JSON file")
    sp.add_argument("--id"); sp.add_argument("--dry-run", action="store_true")
    sp.set_defaults(func=_cmd_campaign)

    sp = sub.add_parser("scrape", help="search/monitor a platform")
    sp.add_argument("platform"); sp.add_argument("query")
    sp.add_argument("--limit", type=int, default=25)
    sp.set_defaults(func=_cmd_scrape)

    sp = sub.add_parser("history", help="what was sent")
    sp.add_argument("--tail", type=int, default=20)
    sp.set_defaults(func=_cmd_history)

    sp = sub.add_parser("server", help="run Ren's web console (needs MARKETING_CONSOLE_TOKEN)")
    sp.add_argument("--host", default="127.0.0.1")
    sp.add_argument("--port", type=int, default=8765)
    sp.set_defaults(func=_cmd_server)

    return p


def main(argv: list[str] | None = None) -> int:
    a = build_parser().parse_args(argv)
    if a.cmd == "campaign" and a.action == "new" and not a.start:
        a.start = timing.to_iso(timing.now())
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
