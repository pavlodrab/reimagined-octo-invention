"""
Tests for the burst-block middleware (PR adds DDoS hardening). The
middleware reads its threshold from the BURST_MAX_REQUESTS env at
import time, so we have to reload the app module after lowering it.
"""
import importlib
import os
import sys

import pytest


@pytest.fixture()
def burst_client(_tmp_db_dir, monkeypatch):
    """Re-import app with a tiny burst threshold and isolated state."""
    monkeypatch.setenv("BURST_MAX_REQUESTS", "5")
    monkeypatch.setenv("BURST_WINDOW_SECONDS", "10")
    monkeypatch.setenv("BURST_BLOCK_SECONDS", "60")
    monkeypatch.setenv("DEMO_MODE", "0")
    monkeypatch.setenv("OWNER_ID", "0")
    monkeypatch.setenv("DB_DIR", str(_tmp_db_dir))
    monkeypatch.setenv("RATE_LIMIT_DEFAULT_PER_MINUTE", "10000 per minute")
    # Reset ALL of app/db so the env values land in module-scope constants.
    for mod in ("app", "db"):
        sys.modules.pop(mod, None)
    import app as appmod  # noqa: WPS433
    try:
        appmod.limiter.reset()
    except Exception:
        pass
    yield appmod.app.test_client()
    # Clean up the imported module so other tests' fixtures get a fresh app.
    for mod in ("app", "db"):
        sys.modules.pop(mod, None)


def test_burst_block_triggers_after_threshold(burst_client):
    """Sending more than BURST_MAX_REQUESTS in the window must yield a 429
    with a Retry-After header. We hit a non-rate-limited path so any
    429 is from the burst middleware, not flask-limiter."""
    statuses = []
    for _ in range(8):  # threshold=5
        r = burst_client.get("/api/config")
        statuses.append(r.status_code)
    # First 5 should pass; at least one of the trailing should be 429.
    assert statuses[:5].count(200) == 5, f"first 5 should all pass: {statuses}"
    assert 429 in statuses[5:], f"expected at least one 429 after threshold: {statuses}"


def test_burst_block_429_carries_retry_after(burst_client):
    """The 429 response must include a Retry-After header so well-behaved
    clients can back off."""
    last = None
    for _ in range(8):
        last = burst_client.get("/api/config")
    if last.status_code == 429:
        assert "Retry-After" in last.headers
        body = last.get_json() or {}
        assert body.get("error") == "rate_limited"


def test_burst_block_exempts_health(burst_client):
    """/api/health is hit by orchestrators (Railway, k8s) much more often
    than the burst threshold. It must never be burst-blocked."""
    statuses = [burst_client.get("/api/health").status_code for _ in range(30)]
    assert all(s == 200 for s in statuses), \
        f"burst middleware blocked health endpoint: {set(statuses)}"
