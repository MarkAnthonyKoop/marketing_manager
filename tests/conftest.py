"""Isolate state under a temp MARKETING_MANAGER_HOME for every test."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKETING_MANAGER_HOME", str(tmp_path))
    yield
