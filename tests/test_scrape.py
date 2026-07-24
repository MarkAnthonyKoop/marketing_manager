"""Scrape forwarding: parses manager JSON, never dies on one bad platform."""
from __future__ import annotations

import subprocess
import types

from marketing_manager import scrape


def _proc(stdout="", stderr="", returncode=0):
    return types.SimpleNamespace(stdout=stdout, stderr=stderr, returncode=returncode)


def test_search_parses_rows(monkeypatch):
    rows = [{"handle": "a", "text": "hi"}]
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: _proc(stdout="[" + '{"handle":"a","text":"hi"}' + "]"))
    out = scrape.search("bluesky", "query")
    assert isinstance(out, list) and out[0]["handle"] == "a"


def test_search_unknown_platform_returns_error_dict():
    out = scrape.search("nope", "q")
    assert "error" in out


def test_run_nonzero_exit_is_error_dict(monkeypatch):
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: _proc(stderr="boom", returncode=1))
    out = scrape.run("bluesky", "search", ["q"])
    assert out["error"] == "boom"


def test_search_many_isolates_failures(monkeypatch):
    def fake(argv, *a, **k):
        if "bluesky_manager" in argv:
            return _proc(stdout="[]")
        return _proc(stderr="denied", returncode=1)
    monkeypatch.setattr(subprocess, "run", fake)
    out = scrape.search_many(["bluesky", "x"], "q")
    assert out["bluesky"] == [] and "error" in out["x"]
