"""
Tests for /api/admin/* authorization (PRs #2, #4) — covers the
auto-grant hole closure plus identity-bypass blocking from PR #5.
"""
import json


# ── Auth gate ──────────────────────────────────────────────────────────

def test_admin_endpoint_requires_auth(client):
    """No auth headers at all -> 401."""
    r = client.get("/api/admin/admins")
    assert r.status_code == 401


def test_admin_endpoint_rejects_non_admin(client, make_init_data):
    """Properly-authenticated NON-admin -> 403."""
    init_data = make_init_data(user_id=99999)
    r = client.get("/api/admin/admins", headers={"X-Init-Data": init_data})
    assert r.status_code == 403


def test_admin_endpoint_accepts_owner(client, make_init_data, make_admin):
    """Owner (set via env-mirroring DB config) should pass."""
    make_admin(54321, owner=True)
    init_data = make_init_data(user_id=54321)
    r = client.get("/api/admin/admins", headers={"X-Init-Data": init_data})
    assert r.status_code == 200
    body = r.get_json()
    assert body and body.get("success") is True


def test_admin_endpoint_accepts_db_admin(client, make_init_data, make_admin):
    """Non-owner but in admins table also passes."""
    make_admin(11111, owner=False)
    init_data = make_init_data(user_id=11111)
    r = client.get("/api/admin/admins", headers={"X-Init-Data": init_data})
    assert r.status_code == 200


def test_no_auto_grant_owner_takeover(client):
    """The OLD vulnerability: when owner_id is 0, any first call would set
    the caller as owner. PR #2 closed this. Hitting an admin endpoint must
    NEVER promote anyone to owner."""
    r = client.post(
        "/api/admin/admins/add",
        headers={"X-Demo-User": json.dumps({"id": 7777})},
        json={"user_id": 1, "username": "victim"},
    )
    # The caller didn't authenticate -> 401. They are NOT now owner.
    assert r.status_code in (401, 403)
    # Verify owner_id wasn't sneakily updated
    import db
    assert db.get_owner_id() == 0, "auto-grant resurrection — owner_id was set!"


# ── End-to-end admin action ────────────────────────────────────────────

def test_admin_can_grant_admin_via_api(client, make_init_data, make_admin):
    """Owner -> /api/admin/admins/add -> new admin appears in list_admins()."""
    make_admin(1000, owner=True)
    owner_init = make_init_data(user_id=1000)

    r = client.post(
        "/api/admin/admins/add",
        headers={"X-Init-Data": owner_init},
        json={"user_id": 2000, "username": "second"},
    )
    assert r.status_code == 200, f"admins/add failed: {r.data}"
    body = r.get_json()
    assert body and body.get("success") is True

    # Now user 2000 should be in the admins table
    import db
    admins = db.list_admins()
    assert any(a["user_id"] == 2000 for a in admins)
