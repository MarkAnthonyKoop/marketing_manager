"""Console API: pure handlers that wire web actions to the engines.

The web console (server.py) is thin HTTP plumbing; the actual work lives here as
plain functions that take a decoded payload (a dict) and return a JSON-able dict.
No HTTP, no auth, no sockets — so every endpoint is unit-testable by calling the
function directly with a temp MARKETING_MANAGER_HOME + a faked poster/brain.

Everything reuses the existing engines (publish/campaigns/schedule/scrape/
store/brain); nothing here re-implements posting or scheduling logic.

Safety default: broadcasts and ticks default to **dry_run=True**. The console
(or a test) must pass dry_run=false explicitly to send for real — a web button
should never post to the world by accident.
"""
from __future__ import annotations

from social_publisher import PLATFORMS, Post, all_keys, working_keys

from . import brain, campaigns, publish, schedule, scrape, store, timing


def _targets(value) -> list[str]:
    """Accept a list of keys, or 'all'/'working', or a comma string."""
    if isinstance(value, list):
        return value
    v = (value or "working").strip().lower()
    if v == "all":
        return all_keys()
    if v == "working":
        return working_keys()
    return [t.strip() for t in v.split(",") if t.strip()]


def _post(payload: dict) -> Post:
    return Post(
        text=payload.get("text", ""),
        media=payload.get("media") or [],
        link=payload.get("link") or None,
        title=payload.get("title") or None,
        tags=payload.get("tags") or [],
    )


def _dry(payload: dict) -> bool:
    # default-safe: only a literal false turns dry-run off
    return payload.get("dry_run", True) is not False


# ---- platforms ----
def platforms() -> dict:
    return {"platforms": [p.__dict__ for p in PLATFORMS],
            "working": working_keys()}


# ---- broadcast ----
def broadcast(payload: dict) -> dict:
    targets = _targets(payload.get("platforms") or payload.get("to"))
    dry = _dry(payload)
    results = publish.send(_post(payload), targets, timing.to_iso(timing.now()),
                           "console", dry_run=dry)
    return {"dry_run": dry, "platforms": targets,
            "results": [r.to_dict() for r in results],
            "summary": publish.summarize(results)}


# ---- campaigns ----
def list_campaigns() -> dict:
    out = []
    for c in store.load_campaigns():
        sent = sum(1 for s in c["steps"] if s["status"] == "sent")
        out.append({"id": c["id"], "name": c["name"], "status": c["status"],
                    "platforms": c["platforms"], "sent": sent,
                    "total": len(c["steps"])})
    return {"campaigns": out}


def create_campaign(payload: dict) -> dict:
    start = payload.get("start_at") or timing.to_iso(timing.now())
    c = campaigns.create(payload["name"], _targets(payload.get("platforms")),
                         start, payload.get("steps") or [])
    return {"created": c["id"], "steps": len(c["steps"])}


def tick_campaigns(payload: dict) -> dict:
    dry = _dry(payload)
    out = campaigns.tick_all(timing.now(), dry_run=dry)
    return {"dry_run": dry, "released": {k: len(v) for k, v in out.items()}}


def campaign_action(cid: str, action: str) -> dict:
    status = {"pause": "paused", "resume": "active"}.get(action)
    if not status:
        return {"error": f"unknown action {action!r}"}
    c = campaigns.set_status(cid, status)
    return {"ok": bool(c), "status": status} if c else {"error": "not found"}


# ---- schedule ----
def list_schedule() -> dict:
    return {"schedule": [{"id": i["id"], "at": i["at"], "status": i["status"],
                          "platforms": i["platforms"], "text": i["text"][:120]}
                         for i in store.load_schedule()]}


def add_schedule(payload: dict) -> dict:
    item = schedule.add(payload["at"], _targets(payload.get("platforms")),
                        payload.get("text", ""), media=payload.get("media") or [],
                        link=payload.get("link"), title=payload.get("title"),
                        tags=payload.get("tags") or [])
    return {"added": item["id"], "at": item["at"]}


def tick_schedule(payload: dict) -> dict:
    dry = _dry(payload)
    acted = schedule.tick(timing.now(), dry_run=dry)
    return {"dry_run": dry, "sent": [i["id"] for i in acted]}


# ---- monitor ----
def history(tail: int = 20) -> dict:
    return {"history": store.read_history(limit=tail)}


def monitor(payload: dict) -> dict:
    """Scrape several platforms for a query → a digest the console renders."""
    query = payload.get("query", "")
    targets = _targets(payload.get("platforms") or "working")
    return {"query": query, "results": scrape.search_many(targets, query,
                                                           limit=payload.get("limit", 15))}


# ---- chat (the AI brain) ----
def chat(payload: dict, ask=brain.ask) -> dict:
    """One turn with the claude-backed brain. `ask` injected for tests."""
    reply = ask(payload.get("message", ""), session_id=payload.get("session_id"))
    return {"reply": reply.text, "session_id": reply.session_id}
