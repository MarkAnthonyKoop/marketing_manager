"""Drip campaigns: a named, ordered sequence of posts released over time.

A campaign anchors at `start_at`; each step has an offset (days/hours) from that
anchor and fires once when due. Ticking a campaign sends every step whose
due-time has passed and that hasn't been sent yet — so a daily cron `tick`
walks a 5-touch sequence out over a week without external state.

Shape (persisted by store.py):
    {id, name, platforms, start_at, status: active|paused|done,
     steps: [{id, offset_days, offset_hours, text, media, link, title, tags,
              status: pending|sent, sent_at, summary}]}

Like schedule.py, the engine takes `now` + a `poster` so it's deterministic.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime

from social_publisher import Post

from . import publish, store, timing


def _slug(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:24] or "campaign"
    return f"{base}-{uuid.uuid4().hex[:4]}"


def create(name: str, platforms: list[str], start_at_iso: str,
           steps: list[dict]) -> dict:
    """Create a campaign. `steps` are partial dicts: at least {text, offset_days}.

    Each step is normalized with defaults + a 'pending' status. Returns the
    stored campaign.
    """
    campaign = {
        "id": _slug(name),
        "name": name,
        "platforms": platforms,
        "start_at": timing.to_iso(timing.parse_iso(start_at_iso)),
        "status": "active",
        "steps": [_norm_step(i, s) for i, s in enumerate(steps)],
    }
    store.upsert_campaign(campaign)
    return campaign


def _norm_step(idx: int, s: dict) -> dict:
    return {
        "id": s.get("id") or f"s{idx + 1}",
        "offset_days": s.get("offset_days", 0),
        "offset_hours": s.get("offset_hours", 0),
        "text": s["text"],
        "media": s.get("media") or [],
        "link": s.get("link"),
        "title": s.get("title"),
        "tags": s.get("tags") or [],
        "status": "pending",
        "sent_at": None,
        "summary": None,
    }


def set_status(cid: str, status: str) -> dict | None:
    """active | paused | done. Paused campaigns are skipped by tick."""
    c = store.get_campaign(cid)
    if not c:
        return None
    c["status"] = status
    store.upsert_campaign(c)
    return c


def step_due_iso(campaign: dict, step: dict) -> str:
    anchor = timing.parse_iso(campaign["start_at"])
    return timing.to_iso(timing.add_offset(anchor, step["offset_days"],
                                           step["offset_hours"]))


def due_steps(campaign: dict, now_dt: datetime) -> list[dict]:
    if campaign["status"] != "active":
        return []
    return [s for s in campaign["steps"]
            if s["status"] == "pending"
            and timing.is_due(step_due_iso(campaign, s), now_dt)]


def _post_from(step: dict) -> Post:
    return Post(text=step["text"], media=step.get("media") or [],
                link=step.get("link"), title=step.get("title"),
                tags=step.get("tags") or [])


def tick_campaign(campaign: dict, now_dt: datetime, dry_run: bool = False,
                  poster=publish.send) -> list[dict]:
    """Send due steps of one campaign; mark them sent; close it when all sent."""
    now_iso = timing.to_iso(now_dt)
    acted: list[dict] = []
    for step in campaign["steps"]:
        if step["status"] != "pending":
            continue
        if not timing.is_due(step_due_iso(campaign, step), now_dt):
            continue
        if campaign["status"] != "active":
            break
        results = poster(_post_from(step), campaign["platforms"], now_iso,
                         f"campaign:{campaign['id']}:{step['id']}", dry_run)
        step["summary"] = publish.summarize(results)
        if not dry_run:
            step["status"] = "sent"
            step["sent_at"] = now_iso
        acted.append(step)
    if not dry_run and all(s["status"] == "sent" for s in campaign["steps"]):
        campaign["status"] = "done"
    store.upsert_campaign(campaign)
    return acted


def tick_all(now_dt: datetime, dry_run: bool = False,
             poster=publish.send) -> dict[str, list[dict]]:
    """Tick every active campaign. Returns {campaign_id: [steps acted on]}."""
    out: dict[str, list[dict]] = {}
    for c in store.load_campaigns():
        if c["status"] != "active":
            continue
        acted = tick_campaign(c, now_dt, dry_run=dry_run, poster=poster)
        if acted:
            out[c["id"]] = acted
    return out
