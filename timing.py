"""Time parsing/formatting shared by the schedule + campaign engines.

Kept separate so both engines (and tests) agree on one timezone-aware ISO
convention. Everything is UTC. Core engine functions take a `now` datetime so
they never read the wall clock themselves — that's what makes them testable;
only the CLI calls `now()`.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone


def now() -> datetime:
    return datetime.now(timezone.utc)


def to_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def parse_iso(s: str) -> datetime:
    """Parse an ISO timestamp to an aware UTC datetime. Accepts trailing 'Z'.

    Naive inputs are assumed UTC (a content calendar with no tz is most usefully
    read as 'whatever UTC instant', and the CLI emits UTC).
    """
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_offset(anchor: datetime, days: float = 0, hours: float = 0) -> datetime:
    return anchor + timedelta(days=days, hours=hours)


def is_due(when_iso: str, now_dt: datetime) -> bool:
    return parse_iso(when_iso) <= now_dt
