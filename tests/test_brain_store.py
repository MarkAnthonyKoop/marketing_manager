"""Brain (claude-CLI wrapper), store, timing, publish — all offline/injected."""
from __future__ import annotations

import json
import types
from datetime import timezone

from social_publisher.model import PostResult

from marketing_manager import brain, chat, publish, store, timing


# ---- timing ----
def test_parse_iso_accepts_z_and_normalizes_utc():
    dt = timing.parse_iso("2026-06-19T12:00:00Z")
    assert dt.tzinfo == timezone.utc and dt.hour == 12


def test_is_due_boundary():
    now = timing.parse_iso("2026-06-19T12:00:00Z")
    assert timing.is_due("2026-06-19T12:00:00Z", now) is True
    assert timing.is_due("2026-06-19T12:00:01Z", now) is False


# ---- store ----
def test_history_roundtrip_and_tail():
    for i in range(3):
        store.append_history({"ts": str(i), "source": "manual", "results": []})
    rows = store.read_history(limit=2)
    assert [r["ts"] for r in rows] == ["1", "2"]


def test_campaign_upsert_replaces_by_id():
    store.upsert_campaign({"id": "c1", "name": "a", "steps": [], "status": "active"})
    store.upsert_campaign({"id": "c1", "name": "b", "steps": [], "status": "active"})
    assert store.get_campaign("c1")["name"] == "b"
    assert len(store.load_campaigns()) == 1


# ---- publish ----
def test_send_logs_history(monkeypatch):
    monkeypatch.setattr(publish, "fan_out",
                        lambda post, plats, dry_run: [PostResult.ok_result(p, "1") for p in plats])
    from social_publisher import Post
    publish.send(Post(text="hi"), ["bluesky"], "now", "manual")
    hist = store.read_history()
    assert hist[-1]["source"] == "manual" and hist[-1]["platforms"] == ["bluesky"]


def test_summarize_counts():
    res = [PostResult.ok_result("a", "1"), PostResult.skip("b", "x"),
           PostResult.fail("c", "e")]
    assert publish.summarize(res) == {"posted": 1, "skipped": 1, "failed": 1, "total": 3}


# ---- brain ----
def _fake_runner(stdout, returncode=0):
    def run(argv, timeout):
        run.argv = argv
        return types.SimpleNamespace(stdout=stdout, stderr="", returncode=returncode)
    return run


def test_ask_parses_result_and_session_id():
    runner = _fake_runner(json.dumps({"result": "hello", "session_id": "sess-1"}))
    reply = brain.ask("hi", runner=runner)
    assert reply.text == "hello" and reply.session_id == "sess-1"
    # first turn injects the system prompt
    assert "--append-system-prompt" in runner.argv


def test_ask_resumes_session_on_followup():
    runner = _fake_runner(json.dumps({"result": "again", "session_id": "sess-1"}))
    brain.ask("more", session_id="sess-1", runner=runner)
    assert "--resume" in runner.argv and "sess-1" in runner.argv
    assert "--append-system-prompt" not in runner.argv


def test_ask_nonzero_exit_raises():
    runner = _fake_runner("", returncode=2)
    try:
        brain.ask("hi", runner=runner)
        assert False, "expected RuntimeError"
    except RuntimeError as e:
        assert "exited 2" in str(e)


def test_ask_tolerates_plain_text_output():
    reply = brain.ask("hi", runner=_fake_runner("not json, just text"))
    assert reply.text == "not json, just text"


# ---- chat REPL ----
def test_repl_exits_on_exit_word(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda _: "exit")
    assert chat.repl() == 0


def test_once_returns_reply_text():
    fake = lambda msg, model=None: types.SimpleNamespace(text="drafted", session_id="s")
    assert chat.once("draft a post", ask=fake) == "drafted"
