"""Durable JSON state for marketing_manager: campaigns, schedule, history.

One small persistence layer so the engines (campaigns.py, schedule.py) and the
CLI don't each reinvent file IO. State lives under a single home dir, override
with MARKETING_MANAGER_HOME (defaults to ~/.local/share/marketing_manager):

    campaigns.json   list[campaign dict]      (drip sequences)
    schedule.json    list[item dict]          (one-off scheduled posts)
    history.jsonl    one JSON object per send  (append-only audit log)

Everything here is plain dict-in/dict-out — no domain logic, no clock, no
network — so it stays trivially testable and the engines own the behavior.
"""
from __future__ import annotations

import json
import os
from pathlib import Path


def home() -> Path:
    p = Path(os.environ.get("MARKETING_MANAGER_HOME",
                            os.path.expanduser("~/.local/share/marketing_manager")))
    p.mkdir(parents=True, exist_ok=True)
    return p


def _path(name: str) -> Path:
    return home() / name


def _load_list(name: str) -> list[dict]:
    p = _path(name)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text())
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def _save_list(name: str, items: list[dict]) -> None:
    tmp = _path(name).with_suffix(".tmp")
    tmp.write_text(json.dumps(items, indent=2))
    tmp.replace(_path(name))  # atomic-ish: write tmp, rename over target


# ---- campaigns ----
def load_campaigns() -> list[dict]:
    return _load_list("campaigns.json")


def save_campaigns(items: list[dict]) -> None:
    _save_list("campaigns.json", items)


def get_campaign(cid: str) -> dict | None:
    return next((c for c in load_campaigns() if c.get("id") == cid), None)


def upsert_campaign(campaign: dict) -> None:
    items = load_campaigns()
    items = [c for c in items if c.get("id") != campaign["id"]]
    items.append(campaign)
    save_campaigns(items)


# ---- schedule ----
def load_schedule() -> list[dict]:
    return _load_list("schedule.json")


def save_schedule(items: list[dict]) -> None:
    _save_list("schedule.json", items)


# ---- history (append-only) ----
def append_history(entry: dict) -> None:
    with _path("history.jsonl").open("a") as f:
        f.write(json.dumps(entry) + "\n")


def read_history(limit: int | None = None) -> list[dict]:
    p = _path("history.jsonl")
    if not p.exists():
        return []
    rows = [json.loads(line) for line in p.read_text().splitlines() if line.strip()]
    return rows[-limit:] if limit else rows
