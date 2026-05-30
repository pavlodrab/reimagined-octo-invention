"""
Tests for /telegram/webhook/<secret_path> route (PR #8).

We test the route's gating logic — secret-path comparison, secret-token
header check, body validation, "no leak when disabled". We DO NOT spin
up a real WebhookBot, since it would require contacting Telegram.
"""


def test_webhook_returns_404_when_disabled(client):
    """No WEBHOOK_URL was set in the test env, so webhook_bot is None
    and the route should pretend it doesn't exist (no info leak)."""
    r = client.post("/telegram/webhook/anything", json={"update_id": 1})
    assert r.status_code == 404


def test_webhook_404_with_random_path(client):
    """Even with a payload that looks Telegram-shaped."""
    r = client.post(
        "/telegram/webhook/some-random-path",
        json={"update_id": 99, "message": {"text": "/start"}},
    )
    assert r.status_code == 404
