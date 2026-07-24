"""The one place marketing_manager actually sends a post — via social_publisher.

Thin wrapper over `social_publisher.fan_out` that also writes a history entry,
so every send (manual, scheduled, or drip) is logged in one audit trail. The
engines (campaigns/schedule) call `send()`; they never import social_publisher
directly. That keeps the dependency on the publishing hub in a single file.

`now_iso` is injected (not read from the clock) so the engines stay
deterministic and testable.
"""
from __future__ import annotations

from social_publisher import Post, fan_out
from social_publisher.model import PostResult

from . import store


def send(post: Post, platforms: list[str], now_iso: str, source: str,
         dry_run: bool = False) -> list[PostResult]:
    """Fan `post` out to `platforms`; log the batch to history. Returns results.

    source is a tag for the audit log: "manual" | "schedule:<id>" |
    "campaign:<id>:<step>". now_iso is the caller's timestamp.
    """
    results = fan_out(post, platforms, dry_run=dry_run)
    store.append_history({
        "ts": now_iso,
        "source": source,
        "dry_run": dry_run,
        "platforms": platforms,
        "text": post.text[:280],
        "results": [r.to_dict() for r in results],
    })
    return results


def summarize(results: list[PostResult]) -> dict:
    """Counts for a batch: posted / skipped / failed."""
    posted = sum(1 for r in results if r.ok and not r.skipped)
    skipped = sum(1 for r in results if r.skipped)
    failed = sum(1 for r in results if not r.ok)
    return {"posted": posted, "skipped": skipped, "failed": failed,
            "total": len(results)}
