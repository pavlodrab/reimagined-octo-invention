"""
Tests for Telegram initData HMAC verification + get_current_user_id
identity-bypass protection (PR #5).
"""
import json
import time


def test_valid_init_data_returns_user(app_module, make_init_data):
    user = app_module.verify_init_data(make_init_data(user_id=42))
    assert user is not None
    assert user["id"] == 42
    assert user["username"] == "tester"


def test_tampered_hash_rejected(app_module, make_init_data):
    valid = make_init_data(user_id=42)
    # Flip the last 2 hex chars of the hash to break the signature
    tampered = valid[:-2] + ("00" if valid[-2:] != "00" else "ff")
    assert app_module.verify_init_data(tampered) is None


def test_stale_init_data_rejected(app_module, make_init_data):
    stale = make_init_data(user_id=42, auth_date=int(time.time()) - 30 * 86400)
    assert app_module.verify_init_data(stale) is None


def test_future_init_data_rejected(app_module, make_init_data):
    """auth_date in the future > 60s skew is suspicious — reject."""
    future = make_init_data(user_id=42, auth_date=int(time.time()) + 3600)
    assert app_module.verify_init_data(future) is None


def test_empty_init_data_returns_none(app_module):
    assert app_module.verify_init_data("") is None
    assert app_module.verify_init_data(None) is None  # type: ignore[arg-type]


def test_init_data_without_token_returns_none(app_module, make_init_data, monkeypatch):
    """If the bot token is missing the signature is unverifiable, so always None."""
    valid = make_init_data(user_id=42)
    monkeypatch.setattr(app_module, "TELEGRAM_TOKEN", "")
    assert app_module.verify_init_data(valid) is None


# ── /api/profile/me as a smoke test for the auth pipeline ──────────────

def test_no_auth_means_no_uid(client):
    """Without X-Init-Data, get_current_user_id() should be None.
    /api/profile/me responds 401 in that case."""
    r = client.get("/api/profile/me")
    # Either 401 explicitly or 4xx — important is that it isn't 200 with a
    # leaked profile (which would mean spoofing worked).
    assert r.status_code in (401, 403, 404)


def test_demo_user_header_ignored_in_production(client):
    """Production-mode app must NOT trust X-Demo-User."""
    r = client.get("/api/profile/me",
                   headers={"X-Demo-User": json.dumps({"id": 999})})
    assert r.status_code in (401, 403, 404)


def test_query_user_id_ignored_in_production(client):
    """Production-mode app must NOT trust ?user_id="""
    r = client.get("/api/profile/me?user_id=999")
    assert r.status_code in (401, 403, 404)


def test_body_user_id_ignored_in_production(client):
    """Body {user_id: ...} fallback was removed entirely. Spoof attempts
    via JSON body should be ignored — admin endpoints should reject."""
    r = client.post("/api/admin/admins/add", json={"user_id": 999})
    # 403 (not admin) is the correct verdict — NOT 200 (spoof worked).
    assert r.status_code in (401, 403)


def test_valid_init_data_authenticates(client, make_init_data):
    """A correctly-signed initData should let get_current_user_id() resolve
    and produce a 200 from /api/profile/me (after profile auto-creation)."""
    init_data = make_init_data(user_id=12345)
    r = client.get("/api/profile/me", headers={"X-Init-Data": init_data})
    # /api/profile/me may auto-create or 404 if profile not seeded; we accept
    # either as long as it's NOT a 401/403 (which would mean auth failed).
    assert r.status_code not in (401, 403), \
        f"valid initData failed to authenticate: {r.status_code}"
