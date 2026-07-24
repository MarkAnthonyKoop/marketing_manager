"""Read/monitor across platforms by forwarding to each manager's read commands.

Posting is unified by social_publisher; *reading* isn't (each platform's data
shape and verbs differ), so marketing_manager forwards to the platform
manager's own read subcommand and returns the parsed JSON. A generic `run`
passthrough handles any verb; `search` maps the common "find posts matching a
query" intent to each platform's search command.

This is best-effort glue — gated platforms whose managers can't read without
creds return an error dict rather than raising, so a monitoring sweep over
several platforms never dies on one.
"""
from __future__ import annotations

import json
import subprocess
import sys

from social_publisher.registry import resolve

# How each platform spells "search for posts matching a query".
# (platform key) -> (subcommand, how to pass the query: "positional" | flag name)
_SEARCH = {
    "bluesky": ("search", "positional"),
    "mastodon": ("search", "positional"),
    "reddit": ("search", "positional"),
    "x": ("search", "positional"),
}


def run(platform: str, subcommand: str, args: list[str] | None = None,
        timeout: int = 60) -> list[dict] | dict:
    """Run `python3 -m <module> <subcommand> [args] --json` and parse stdout.

    Returns the parsed JSON (list of rows) or {"error": "..."} on failure.
    """
    try:
        mod = resolve(platform).module
    except KeyError as e:
        return {"error": str(e)}
    argv = [sys.executable, "-m", mod, subcommand, *(args or []), "--json"]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"error": f"{platform} {subcommand} timed out"}
    if proc.returncode != 0:
        return {"error": (proc.stderr or proc.stdout or "failed").strip()[:300]}
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"error": f"non-JSON output: {proc.stdout.strip()[:200]}"}


def search(platform: str, query: str, limit: int = 25) -> list[dict] | dict:
    """Search one platform for `query`. Returns rows or an error dict."""
    if platform not in _SEARCH:
        return {"error": f"{platform} has no search command wired in scrape.py"}
    sub, how = _SEARCH[platform]
    args = [query] if how == "positional" else [f"--{how}", query]
    args += ["--limit", str(limit)]
    return run(platform, sub, args)


def search_many(platforms: list[str], query: str,
                limit: int = 25) -> dict[str, list[dict] | dict]:
    """Search several platforms for the same query. {platform: rows|error}."""
    return {p: search(p, query, limit=limit) for p in platforms}
