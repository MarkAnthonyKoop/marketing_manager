"""Schedule + campaign engines: due detection, sending, idempotency, sequencing.

Deterministic: we inject a fixed `now` and a fake poster (no network, no clock).
The fake poster records calls and returns a fixed PostResult list.
"""
from __future__ import annotations

from datetime import timedelta

from social_publisher.model import PostResult

from marketing_manager import campaigns, schedule, store, timing


def _poster_factory(calls):
    def fake(post, platforms, now_iso, source, dry_run):
        calls.append({"text": post.text, "platforms": platforms,
                      "source": source, "dry_run": dry_run})
        return [PostResult.ok_result(p, "id") for p in platforms]
    return fake


# ---- schedule ----
def test_schedule_add_then_due_and_tick_sends_once():
    calls = []
    now = timing.now()
    past = timing.to_iso(now - timedelta(hours=1))
    schedule.add(past, ["bluesky"], "scheduled body")

    assert len(schedule.due(now)) == 1
    acted = schedule.tick(now, poster=_poster_factory(calls))
    assert len(acted) == 1 and len(calls) == 1
    assert acted[0]["status"] == "sent"
    # second tick: already sent → no resend
    acted2 = schedule.tick(now, poster=_poster_factory(calls))
    assert acted2 == [] and len(calls) == 1


def test_schedule_future_item_not_due():
    now = timing.now()
    future = timing.to_iso(now + timedelta(days=2))
    schedule.add(future, ["mastodon"], "later")
    assert schedule.due(now) == []


def test_schedule_dry_run_does_not_mark_sent():
    calls = []
    now = timing.now()
    schedule.add(timing.to_iso(now - timedelta(minutes=5)), ["bluesky"], "x")
    acted = schedule.tick(now, dry_run=True, poster=_poster_factory(calls))
    assert acted[0]["status"] == "pending" and calls[0]["dry_run"] is True


# ---- campaigns ----
def _campaign(now):
    return campaigns.create(
        "Launch", ["bluesky", "mastodon"], timing.to_iso(now),
        steps=[{"offset_days": 0, "text": "day 0"},
               {"offset_days": 1, "text": "day 1"},
               {"offset_days": 3, "text": "day 3"}],
    )


def test_campaign_releases_steps_as_time_passes():
    calls = []
    start = timing.now()
    c = _campaign(start)

    # at start: only step 0 is due
    campaigns.tick_campaign(store.get_campaign(c["id"]), start, poster=_poster_factory(calls))
    sent = [s for s in store.get_campaign(c["id"])["steps"] if s["status"] == "sent"]
    assert len(sent) == 1 and len(calls) == 1

    # +1 day: step 1 also due (step 0 not resent)
    campaigns.tick_campaign(store.get_campaign(c["id"]), start + timedelta(days=1),
                            poster=_poster_factory(calls))
    assert len(calls) == 2

    # +3 days: final step → campaign closes
    campaigns.tick_campaign(store.get_campaign(c["id"]), start + timedelta(days=3),
                            poster=_poster_factory(calls))
    final = store.get_campaign(c["id"])
    assert len(calls) == 3 and final["status"] == "done"


def test_paused_campaign_does_not_fire():
    calls = []
    start = timing.now()
    c = _campaign(start)
    campaigns.set_status(c["id"], "paused")
    out = campaigns.tick_all(start, poster=_poster_factory(calls))
    assert out == {} and calls == []


def test_each_step_posts_to_campaign_platforms():
    calls = []
    start = timing.now()
    c = _campaign(start)
    campaigns.tick_campaign(store.get_campaign(c["id"]), start, poster=_poster_factory(calls))
    assert calls[0]["platforms"] == ["bluesky", "mastodon"]
    assert calls[0]["source"].startswith(f"campaign:{c['id']}:")
