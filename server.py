"""Ren's web console — a mobile-first remote control for the marketing engine.

Ren has no Claude Code access (just an iPad/iPhone), so this serves a small
single-page console he drives over the web: compose & broadcast, drip campaigns,
schedule, and monitor. It's deliberately **stdlib-only** (`http.server`) — no
Flask, no new dependency — and thin: every route just calls a function in
`api.py`, which calls the existing engines. The console.html SPA is the UI.

Security (default-deny): the server refuses to start unless
`MARKETING_CONSOLE_TOKEN` is set in the environment, and every `/api/*` request
must present that token in the `X-Console-Token` header (constant-time compared).
The HTML shell and `/healthz` are the only unauthenticated routes. Never hardcode
the token (cf. the committed ElevenLabs key in livingcolor — not here).

Deploy contract (remote_server §4): `python3 -m marketing_manager server --port $PORT`.
"""
from __future__ import annotations

import hmac
import json
import os
import socketserver
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import api

TOKEN_ENV = "MARKETING_CONSOLE_TOKEN"
_HTML = Path(__file__).parent / "console.html"
# Static assets split out of the HTML so the edge CSP needs no 'unsafe-inline':
# the page carries zero inline script/style (see console.html header comment).
_ASSETS = {"/console.js": ("console.js", "text/javascript; charset=utf-8"),
           "/console.css": ("console.css", "text/css; charset=utf-8")}


def _token() -> str | None:
    return os.environ.get(TOKEN_ENV)


class ConsoleHandler(BaseHTTPRequestHandler):
    server_version = "marketing_console/0.1"

    # ---- helpers ----
    def _json(self, obj, status=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authed(self) -> bool:
        tok = _token()
        got = self.headers.get("X-Console-Token", "")
        return bool(tok) and hmac.compare_digest(got, tok)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length", 0) or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            return {}

    def log_message(self, *a):  # quiet; don't spam stdout per request
        pass

    # ---- routing ----
    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            return self._serve_html()
        if path in _ASSETS:
            return self._serve_asset(path)
        if path == "/healthz":
            return self._json({"ok": True})
        if not path.startswith("/api/"):
            return self._json({"error": "not found"}, 404)
        if not self._authed():
            return self._json({"error": "unauthorized"}, 401)
        qs = parse_qs(urlparse(self.path).query)
        try:
            if path == "/api/platforms":
                return self._json(api.platforms())
            if path == "/api/guide":
                return self._json(api.guide())
            if path == "/api/campaigns":
                return self._json(api.list_campaigns())
            if path == "/api/schedule":
                return self._json(api.list_schedule())
            if path == "/api/history":
                return self._json(api.history(int(qs.get("tail", ["20"])[0])))
            return self._json({"error": "not found"}, 404)
        except Exception as e:  # noqa: BLE001 — never crash the server
            return self._json({"error": f"{type(e).__name__}: {e}"}, 500)

    def do_POST(self):
        path = urlparse(self.path).path
        if not path.startswith("/api/"):
            return self._json({"error": "not found"}, 404)
        if not self._authed():
            return self._json({"error": "unauthorized"}, 401)
        body = self._body()
        try:
            return self._json(self._dispatch_post(path, body))
        except KeyError as e:
            return self._json({"error": f"missing field {e}"}, 400)
        except Exception as e:  # noqa: BLE001
            return self._json({"error": f"{type(e).__name__}: {e}"}, 500)

    def _dispatch_post(self, path: str, body: dict) -> dict:
        if path == "/api/broadcast":
            return api.broadcast(body)
        if path == "/api/campaigns":
            return api.create_campaign(body)
        if path == "/api/campaigns/tick":
            return api.tick_campaigns(body)
        if path == "/api/schedule":
            return api.add_schedule(body)
        if path == "/api/schedule/tick":
            return api.tick_schedule(body)
        if path == "/api/monitor":
            return api.monitor(body)
        if path == "/api/chat":
            return api.chat(body)
        parts = path.strip("/").split("/")  # api/campaigns/<id>/<action>
        if len(parts) == 4 and parts[:2] == ["api", "campaigns"]:
            return api.campaign_action(parts[2], parts[3])
        return {"error": "not found"}

    def _serve_html(self):
        try:
            html = _HTML.read_bytes()
        except FileNotFoundError:
            html = b"<h1>console.html missing</h1>"
        self._send_static(html, "text/html; charset=utf-8")

    def _serve_asset(self, path: str):
        name, ctype = _ASSETS[path]
        try:
            body = (Path(__file__).parent / name).read_bytes()
        except FileNotFoundError:
            return self._json({"error": "not found"}, 404)
        self._send_static(body, ctype)

    def _send_static(self, body: bytes, ctype: str):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        # no-cache: a stale cached page referencing old inline script would be
        # broken by the strict CSP after a deploy — always revalidate.
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)


class _ConsoleServer(ThreadingHTTPServer):
    """ThreadingHTTPServer without the getfqdn() reverse-DNS in server_bind.

    Stock HTTPServer.server_bind calls socket.getfqdn(host) to set server_name,
    which can block for tens of seconds on networks with slow reverse DNS. We
    don't use server_name, so skip it — startup is instant.
    """
    def server_bind(self):
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = host
        self.server_port = port


def make_server(host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    """Build the server. Raises if the auth token isn't configured (default-deny)."""
    if not _token():
        raise RuntimeError(
            f"refusing to start: set {TOKEN_ENV} (a shared secret only Ren knows). "
            "The console is default-deny — no token, no server.")
    return _ConsoleServer((host, port), ConsoleHandler)


def serve(host: str = "127.0.0.1", port: int = 8765) -> None:
    srv = make_server(host, port)
    print(f"marketing console on http://{host}:{port}  (token auth on)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()
