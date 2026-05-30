"""
Tests for the rate-limiter (PR #6) — covers per-route tighter limits
plus the exempted endpoints. Default global limit is set to a huge
value in conftest so it doesn't accidentally trip during these tests.
"""
import json
import pytest


def test_admin_admins_add_is_rate_limited(client, make_init_data, make_admin):
    """The 5/min limit on /api/admin/admins/add must trigger before 10
    requests, even when the caller IS an authenticated admin."""
    # Authenticate as owner so we get past the auth gate; the rate-limit
    # decorator runs BEFORE the view, so even valid requests count.
    make_admin(70001, owner=True)
    init = make_init_data(user_id=70001)

    statuses = []
    for i in range(8):
        r = client.post(
            "/api/admin/admins/add",
            headers={"X-Init-Data": init},
            json={"user_id": 80000 + i, "username": f"u{i}"},
        )
        statuses.append(r.status_code)

    # First 5 should NOT be 429; later requests should include 429.
    assert statuses.count(429) >= 1, \
        f"expected at least one 429, got {statuses}"


def test_health_endpoint_is_exempt(client):
    """/api/health is hit by Railway's healthcheck constantly — must never
    return 429."""
    statuses = [client.get("/api/health").status_code for _ in range(50)]
    assert all(s == 200 for s in statuses), \
        f"health endpoint rate-limited: {set(statuses)}"


def test_rate_limit_is_per_user(client, make_init_data, make_admin):
    """Two different authenticated admins should have independent counters."""
    make_admin(60001, owner=True)
    make_admin(60002, owner=False)

    a_init = make_init_data(user_id=60001)
    b_init = make_init_data(user_id=60002)

    # Exhaust user 60001's quota on /api/admin/admins/add (5/min)
    for _ in range(7):
        client.post(
            "/api/admin/admins/add",
            headers={"X-Init-Data": a_init},
            json={"user_id": 12345, "username": "foo"},
        )

    # User 60002's first hit must still get through (not 429)
    r = client.post(
        "/api/admin/admins/add",
        headers={"X-Init-Data": b_init},
        json={"user_id": 99999, "username": "bar"},
    )
    assert r.status_code != 429, \
        f"per-user keying broken: 60002 got 429 right after 60001's burst"


def test_rate_limit_response_headers(client, make_init_data, make_admin):
    """X-RateLimit-* headers should appear on responses for limited routes."""
    make_admin(60003, owner=True)
    init = make_init_data(user_id=60003)
    r = client.post(
        "/api/admin/admins/add",
        headers={"X-Init-Data": init},
        json={"user_id": 11111},
    )
    # The headers come from flask-limiter when headers_enabled=True
    assert "X-RateLimit-Limit" in r.headers, \
        f"missing X-RateLimit-Limit header in response: {dict(r.headers)}"
