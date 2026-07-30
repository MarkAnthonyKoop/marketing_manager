"""Web console HTTP layer: default-deny, token auth, routing. Real loopback server.

Spins up the stdlib server on an ephemeral port in a thread and hits it with
urllib (no extra deps). publish.fan_out is stubbed so broadcasts touch no network.
"""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

import pytest

from social_publisher.model import PostResult

from marketing_manager import publish, server

TOKEN = "secret-test-token"


@pytest.fixture
def live_server(monkeypatch):
    monkeypatch.setenv("MARKETING_CONSOLE_TOKEN", TOKEN)
    monkeypatch.setattr(publish, "fan_out",
                        lambda post, plats, dry_run: [PostResult.ok_result(p, "1") for p in plats])
    srv = server.make_server("127.0.0.1", 0)
    port = srv.server_address[1]
    t = threading.Thread(target=lambda: srv.serve_forever(poll_interval=0.05), daemon=True)
    t.start()
    yield f"http://127.0.0.1:{port}"
    srv.shutdown()


def _req(url, method="GET", token=None, body=None):
    headers = {}
    if token:
        headers["X-Console-Token"] = token
    data = json.dumps(body).encode() if body is not None else None
    if data:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, method=method, headers=headers, data=data)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            ctype = r.headers.get_content_type()
            raw = r.read()
            body = json.loads(raw or b"null") if ctype == "application/json" else None
            return r.status, body, ctype
    except urllib.error.HTTPError as e:
        ctype = e.headers.get_content_type()
        body = json.loads(e.read() or b"null") if ctype == "application/json" else None
        return e.code, body, ctype


def test_make_server_refuses_without_token(monkeypatch):
    monkeypatch.delenv("MARKETING_CONSOLE_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="refusing to start"):
        server.make_server("127.0.0.1", 0)


def test_healthz_is_public(live_server):
    status, body, _ = _req(live_server + "/healthz")
    assert status == 200 and body["ok"] is True


def test_root_serves_html(live_server):
    status, _, ctype = _req(live_server + "/")
    assert status == 200 and ctype == "text/html"


def test_api_requires_token(live_server):
    status, body, _ = _req(live_server + "/api/platforms")  # no token
    assert status == 401 and body["error"] == "unauthorized"


def test_api_rejects_wrong_token(live_server):
    status, _, _ = _req(live_server + "/api/platforms", token="nope")
    assert status == 401


def test_platforms_with_token(live_server):
    status, body, _ = _req(live_server + "/api/platforms", token=TOKEN)
    assert status == 200 and "bluesky" in body["working"]


def test_broadcast_roundtrip_dry(live_server):
    status, body, _ = _req(live_server + "/api/broadcast", method="POST", token=TOKEN,
                           body={"text": "hi", "platforms": ["bluesky"], "dry_run": True})
    assert status == 200 and body["dry_run"] is True and body["summary"]["total"] == 1


def test_campaign_create_and_list_over_http(live_server):
    s, b, _ = _req(live_server + "/api/campaigns", method="POST", token=TOKEN,
                   body={"name": "HTTP", "platforms": ["bluesky"],
                         "steps": [{"offset_days": 0, "text": "go"}]})
    assert s == 200 and b["created"]
    s, b, _ = _req(live_server + "/api/campaigns", token=TOKEN)
    assert b["campaigns"][0]["name"] == "HTTP"


def test_unknown_route_404(live_server):
    status, _, _ = _req(live_server + "/api/nope", token=TOKEN)
    assert status == 404


def test_guide_requires_token(live_server):
    status, body, _ = _req(f"{live_server}/api/guide")
    assert status == 401


def test_guide_route_returns_branding(live_server, monkeypatch, tmp_path):
    md = tmp_path / "g.md"
    md.write_text("# Hi\n", encoding="utf-8")
    monkeypatch.setenv("MARKETING_CONSOLE_GUIDE", str(md))
    monkeypatch.setenv("MARKETING_CONSOLE_BRAND", "RenWay")
    status, body, _ = _req(f"{live_server}/api/guide", token=TOKEN)
    assert status == 200
    assert body["brand"] == "RenWay" and body["markdown"] == "# Hi\n"


def test_html_shell_has_onboarding(live_server):
    import urllib.request
    with urllib.request.urlopen(f"{live_server}/", timeout=10) as r:
        html = r.read().decode()
    assert 'id="wel"' in html and "startTour" in html and 'id="t-guide"' in html
