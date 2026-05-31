"""
Shared pytest fixtures for the Chelsea Voting Bot test suite.

Test-time configuration:
- DEMO_MODE=0 (production-style auth — verified initData only)
- TELEGRAM_TOKEN: a known fixed value so we can forge valid initData
- SQLite in a per-session temp dir (no real Postgres needed)
- Generous rate-limit defaults so accidental limiting doesn't pollute
  unrelated tests; per-route tighter limits (e.g. 5/min for admin/admins/add)
  remain in effect for the dedicated rate-limit tests.
"""

from __future__ import annotations

import hashlib
import hmac as _hmac
import importlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode

import pytest

TEST_BOT_TOKEN = "1234567:TEST_TOKEN_FOR_PYTEST_ONLY"


def _set_test_env(tmp_db_dir: Path) -> None:
    os.environ["TELEGRAM_TOKEN"] = TEST_BOT_TOKEN
    os.environ["DEMO_MODE"] = "0"
    os.environ["OWNER_ID"] = "0"  # tests bootstrap owner manually via DB
    os.environ["DB_DIR"] = str(tmp_db_dir)
    os.environ.pop("DATABASE_URL", None)
    os.environ.pop("WEBHOOK_URL", None)
    os.environ.pop("SENTRY_DSN", None)
    # High global default — individual per-route limits still apply
    os.environ["RATE_LIMIT_DEFAULT_PER_MINUTE"] = "10000 per minute"
    os.environ["RATE_LIMIT_DEFAULT_PER_HOUR"] = "1000000 per hour"
    # Disable the burst-block window during tests; the dedicated
    # test_burst_block.py overrides this back to a small value.
    os.environ["BURST_MAX_REQUESTS"] = "100000"


def _reload_modules() -> None:
    """Force a fresh import of app/db/etc. so module-level code runs with the
    current env. Pytest collects tests after the test runner imports them, so
    we have to evict cached imports."""
    for mod in ("app", "db", "logging_setup", "webhook", "bot"):
        sys.modules.pop(mod, None)


# ── Session-scoped: app + client ───────────────────────────────────────

@pytest.fixture(scope="session")
def _tmp_db_dir(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("db")


@pytest.fixture(scope="session")
def app_module(_tmp_db_dir):
    """Imported app module. Session-scoped so we don't pay reimport cost
    every test. State (rate-limiter, DB) is reset per-test via other
    fixtures."""
    _set_test_env(_tmp_db_dir)
    _reload_modules()
    import app as appmod  # noqa: WPS433 — late import is intentional
    return appmod


@pytest.fixture()
def client(app_module):
    """Flask test client with rate-limit counters reset per-test."""
    # Drop limiter counters between tests so a previous test's bursts
    # don't bleed into this one.
    try:
        app_module.limiter.reset()
    except Exception:
        pass
    return app_module.app.test_client()


@pytest.fixture()
def db_module(app_module):
    """Direct access to the db module (already imported and initialised)."""
    import db
    return db


@pytest.fixture(autouse=True)
def _reset_db_state(db_module):
    """Wipe mutable tables between tests so admin/votes from one test
    don't leak into another. We DON'T drop the schema — just clear rows."""
    yield
    conn = db_module.get_connection()
    try:
        for table in ("admins", "votes", "polls", "predictions", "challenges",
                      "challenge_progress", "user_xp", "streaks", "match_events",
                      "ai_ratings", "awards", "match_analytics", "match_reports",
                      "admin_logs"):
            try:
                conn.execute(f"DELETE FROM {table}")
            except Exception:
                pass
        # Reset api_error_count + owner_id config keys we mutate during tests
        conn.execute("UPDATE config SET value='0' WHERE key='api_error_count'")
        conn.execute("UPDATE config SET value='0' WHERE key='owner_id'")
        conn.commit()
    finally:
        conn.close()


# ── initData factory ───────────────────────────────────────────────────

@pytest.fixture()
def make_init_data():
    """Returns a function that builds a valid Telegram-style initData query
    string for a given user_id. Uses TEST_BOT_TOKEN so app.verify_init_data
    will accept it."""

    def _make(user_id: int = 42, auth_date: Optional[int] = None,
              username: str = "tester", first_name: str = "Test") -> str:
        if auth_date is None:
            auth_date = int(time.time())
        user = json.dumps(
            {"id": user_id, "username": username, "first_name": first_name},
            separators=(",", ":"),
        )
        fields = {"auth_date": str(auth_date), "query_id": "q123", "user": user}
        pairs = sorted(f"{k}={v}" for k, v in fields.items())
        data_check_string = "\n".join(pairs)
        secret = _hmac.new(b"WebAppData", TEST_BOT_TOKEN.encode(),
                           hashlib.sha256).digest()
        sig = _hmac.new(secret, data_check_string.encode(),
                        hashlib.sha256).hexdigest()
        fields["hash"] = sig
        return urlencode(fields)

    return _make


@pytest.fixture()
def make_admin(db_module, app_module):
    """Returns a function that bootstraps a user as admin (or owner) in the
    DB. Use when you need an authenticated admin to talk to /api/admin/*."""

    def _grant(user_id: int, *, owner: bool = False) -> int:
        if owner:
            db_module.set_config("owner_id", str(user_id))
        else:
            db_module.add_admin(user_id, "tester", added_by=user_id)
        return user_id

    return _grant
