"""Console API handlers — engine wiring, dry-run-by-default, no HTTP. Offline."""
from __future__ import annotations

import types

from social_publisher.model import PostResult

from marketing_manager import api, publish, scrape, store, timing


def _ok_fanout(post, platforms, dry_run):
    return [PostResult.ok_result(p, "id", f"http://{p}/1") for p in platforms]


def test_platforms_lists_with_working():
    d = api.platforms()
    assert any(p["key"] == "bluesky" for p in d["platforms"])
    assert "bluesky" in d["working"]


def test_broadcast_defaults_to_dry_run(monkeypatch):
    monkeypatch.setattr(publish, "fan_out", _ok_fanout)
    d = api.broadcast({"text": "hi", "platforms": ["bluesky"]})
    assert d["dry_run"] is True            # safety: no explicit false → dry
    assert d["summary"]["total"] == 1
    # history logged
    assert store.read_history()[-1]["source"] == "console"


def test_broadcast_real_send_requires_explicit_false(monkeypatch):
    seen = {}
    def cap(post, platforms, dry_run):
        seen["dry"] = dry_run
        return _ok_fanout(post, platforms, dry_run)
    monkeypatch.setattr(publish, "fan_out", cap)
    api.broadcast({"text": "hi", "platforms": ["bluesky"], "dry_run": False})
    assert seen["dry"] is False


def test_broadcast_targets_keywords(monkeypatch):
    monkeypatch.setattr(publish, "fan_out", _ok_fanout)
    d = api.broadcast({"text": "hi", "platforms": "working"})
    assert "bluesky" in d["platforms"] and "x" not in d["platforms"]


def test_campaign_create_list_and_action():
    api.create_campaign({"name": "Launch", "platforms": ["bluesky"],
                         "steps": [{"offset_days": 0, "text": "go"}]})
    lst = api.list_campaigns()["campaigns"]
    assert lst[0]["name"] == "Launch" and lst[0]["total"] == 1
    cid = lst[0]["id"]
    assert api.campaign_action(cid, "pause")["status"] == "paused"
    assert store.get_campaign(cid)["status"] == "paused"
    assert "error" in api.campaign_action(cid, "bogus")


def test_campaign_tick_dry_by_default(monkeypatch):
    monkeypatch.setattr(publish, "fan_out", _ok_fanout)
    api.create_campaign({"name": "C", "platforms": ["bluesky"],
                         "start_at": timing.to_iso(timing.now()),
                         "steps": [{"offset_days": 0, "text": "now"}]})
    d = api.tick_campaigns({})
    assert d["dry_run"] is True and sum(d["released"].values()) == 1
    # dry-run didn't mark sent
    assert all(s["status"] == "pending"
               for c in store.load_campaigns() for s in c["steps"])


def test_schedule_add_list_tick(monkeypatch):
    monkeypatch.setattr(publish, "fan_out", _ok_fanout)
    past = timing.to_iso(timing.now())
    api.add_schedule({"at": past, "platforms": ["bluesky"], "text": "due"})
    assert api.list_schedule()["schedule"][0]["status"] == "pending"
    d = api.tick_schedule({"dry_run": False})
    assert len(d["sent"]) == 1
    assert api.list_schedule()["schedule"][0]["status"] == "sent"


def test_history_returns_recent(monkeypatch):
    monkeypatch.setattr(publish, "fan_out", _ok_fanout)
    api.broadcast({"text": "one", "platforms": ["bluesky"]})
    assert api.history(5)["history"][-1]["text"] == "one"


def test_monitor_uses_scrape(monkeypatch):
    monkeypatch.setattr(scrape, "search_many",
                        lambda plats, q, limit=15: {p: [{"text": q}] for p in plats})
    d = api.monitor({"query": "brand", "platforms": ["bluesky"]})
    assert d["results"]["bluesky"][0]["text"] == "brand"


def test_chat_injectable_ask():
    fake = lambda message, session_id=None: types.SimpleNamespace(text="drafted", session_id="s1")
    d = api.chat({"message": "draft"}, ask=fake)
    assert d["reply"] == "drafted" and d["session_id"] == "s1"


# ---- guide / onboarding ----
def test_guide_defaults_when_unconfigured(monkeypatch):
    for v in ("MARKETING_CONSOLE_GUIDE", "MARKETING_CONSOLE_BRAND",
              "MARKETING_CONSOLE_GREETING"):
        monkeypatch.delenv(v, raising=False)
    d = api.guide()
    assert d["brand"] == "Marketing Console"
    assert "Marketing Console" in d["greeting"]
    assert d["missing"] is True and "markdown" not in d


def test_guide_serves_branded_markdown(tmp_path, monkeypatch):
    md = tmp_path / "GUIDE.md"
    md.write_text("# Hello Ren\n\n- be brave\n", encoding="utf-8")
    monkeypatch.setenv("MARKETING_CONSOLE_GUIDE", str(md))
    monkeypatch.setenv("MARKETING_CONSOLE_BRAND", "RenWay")
    monkeypatch.setenv("MARKETING_CONSOLE_GREETING", "Hey, I'm RenWay.")
    d = api.guide()
    assert d == {"brand": "RenWay", "greeting": "Hey, I'm RenWay.",
                 "markdown": "# Hello Ren\n\n- be brave\n"}


def test_guide_missing_file_degrades(monkeypatch, tmp_path):
    monkeypatch.setenv("MARKETING_CONSOLE_GUIDE", str(tmp_path / "nope.md"))
    d = api.guide()
    assert d["missing"] is True
