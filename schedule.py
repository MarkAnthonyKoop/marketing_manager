"""Content calendar: one-off posts scheduled for a future time.

A scheduled item is "post THIS to THESE platforms AT this time, once." The
engine's job is to persist items and, when ticked, send the ones whose time has
come. The drip-campaign engine (campaigns.py) handles multi-step sequences;
this is the simpler single-shot calendar.

Core functions take `now` (a datetime) and a `poster` callable so they're
deterministic in tests — the CLI passes `timing.now()` and `publish.send`.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime

from social_publisher import Post

from . import publish, store, timing


def _slug(text: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:24] or "post"
    return f"{base}-{uuid.uuid4().hex[:6]}"


def add(at_iso: str, platforms: list[str], text: str, media: list[str] | None = None,
        link: str | None = None, title: str | None = None,
        tags: list[str] | None = None) -> dict:
    """Add a scheduled post. `at_iso` is parsed/normalized to UTC. Returns it."""
    item = {
        "id": _slug(text),
        "at": timing.to_iso(timing.parse_iso(at_iso)),
        "platforms": platforms,
        "text": text,
        "media": media or [],
        "link": link,
        "title": title,
        "tags": tags or [],
        "status": "pending",
        "sent_at": None,
        "summary": None,
    }
    items = store.load_schedule()
    items.append(item)
    store.save_schedule(items)
    return item


def remove(item_id: str) -> bool:
    items = store.load_schedule()
    kept = [i for i in items if i["id"] != item_id]
    store.save_schedule(kept)
    return len(kept) != len(items)


def due(now_dt: datetime) -> list[dict]:
    """Pending items whose time has arrived."""
    return [i for i in store.load_schedule()
            if i["status"] == "pending" and timing.is_due(i["at"], now_dt)]


def _post_from(item: dict) -> Post:
    return Post(text=item["text"], media=item.get("media") or [],
                link=item.get("link"), title=item.get("title"),
                tags=item.get("tags") or [])


def tick(now_dt: datetime, dry_run: bool = False, poster=publish.send) -> list[dict]:
    """Send every due item once; mark it sent. Returns the items acted on.

    `poster(post, platforms, now_iso, source, dry_run)` defaults to publish.send;
    tests inject a fake. Idempotent: an item flips to 'sent' so a second tick in
    the same window won't repost it.
    """
    now_iso = timing.to_iso(now_dt)
    items = store.load_schedule()
    acted: list[dict] = []
    for item in items:
        if item["status"] != "pending" or not timing.is_due(item["at"], now_dt):
            continue
        results = poster(_post_from(item), item["platforms"], now_iso,
                         f"schedule:{item['id']}", dry_run)
        item["summary"] = publish.summarize(results)
        if not dry_run:
            item["status"] = "sent"
            item["sent_at"] = now_iso
        acted.append(item)
    store.save_schedule(items)
    return acted
