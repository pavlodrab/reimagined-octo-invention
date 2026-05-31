"""
Tests for the Chelsea CAPTCHA — challenge endpoint, verify endpoint,
and the first-vote gate it backs.
"""
import json

import pytest


# ── Pure-module helpers (no Flask round-trip) ──────────────────────────

def test_generate_challenge_returns_signed_token(app_module):
    """The challenge endpoint must always return a (token, options)
    pair with the answer index hidden in the token, never in the body."""
    import captcha as c
    ch = c.generate_challenge()
    assert ch["type"] in ("crest", "trivia")
    assert "challenge_token" in ch
    assert "options" in ch and len(ch["options"]) == 4
    # The correct index lives in the signed token, NOT in the public
    # body — make sure neither the body nor any option exposes it.
    assert "correct" not in ch
    for opt in ch["options"]:
        if isinstance(opt, dict):
            assert "correct" not in opt


def test_verify_correct_answer(app_module, monkeypatch):
    """A challenge solved with the right index must verify OK."""
    import captcha as c
    ch = c.generate_challenge()
    # Reach into the signed token to discover the correct index
    # (test-only — clients never see this).
    payload = c._unsign(ch["challenge_token"])
    assert payload is not None
    correct_idx = payload["correct"]
    assert c.verify_challenge_answer(ch["challenge_token"], correct_idx) == c.CaptchaResult.OK


def test_verify_wrong_answer(app_module):
    import captcha as c
    ch = c.generate_challenge()
    payload = c._unsign(ch["challenge_token"])
    wrong = (payload["correct"] + 1) % 4
    assert c.verify_challenge_answer(ch["challenge_token"], wrong) == c.CaptchaResult.WRONG_ANSWER


def test_verify_tampered_token(app_module):
    """Mutating any byte of the token must invalidate the signature."""
    import captcha as c
    ch = c.generate_challenge()
    # Flip a byte in the payload portion (before the dot).
    body, sig = ch["challenge_token"].split(".", 1)
    mutated = body[:-1] + ("A" if body[-1] != "A" else "B") + "." + sig
    assert c.verify_challenge_answer(mutated, 0) == c.CaptchaResult.BAD_SIGNATURE


def test_verify_expired_token(app_module, monkeypatch):
    """A challenge token must reject answers after its expiry."""
    import captcha as c
    # Force the issued token to expire immediately by stubbing time.
    real_time = c.time.time
    monkeypatch.setattr(c.time, "time", lambda: real_time() - 1000)
    ch = c.generate_challenge()
    monkeypatch.setattr(c.time, "time", real_time)
    payload = c._unsign(ch["challenge_token"])
    assert c.verify_challenge_answer(ch["challenge_token"], payload["correct"]) == c.CaptchaResult.EXPIRED


def test_proof_token_is_uid_bound(app_module):
    """A proof minted for user A must NOT verify for user B."""
    import captcha as c
    proof = c.issue_proof(42)
    assert c.verify_proof(proof, 42) is True
    assert c.verify_proof(proof, 43) is False
    assert c.verify_proof("garbage", 42) is False


# ── Endpoint tests via the Flask test client ───────────────────────────

def test_challenge_endpoint_returns_payload(client):
    r = client.get("/api/captcha/challenge")
    assert r.status_code == 200
    body = r.get_json()
    assert body["success"] is True
    assert "challenge" in body
    assert body["challenge"]["type"] in ("crest", "trivia")


def test_verify_endpoint_requires_auth(client):
    r = client.post("/api/captcha/verify", json={"challenge_token": "x", "answer": 0})
    assert r.status_code == 401


def test_first_vote_gate_returns_412_without_proof(client, make_init_data, db_module):
    """A brand-new user (no votes ever) must get a 412 from vote_batch
    without a proof header. The body shape must include captcha:true so
    the client knows to open the modal."""
    init = make_init_data(user_id=88001)

    # Seed a poll so vote_batch finds it open. (Otherwise the 412
    # check would only fire after the poll-not-found 404 — our gate
    # runs BEFORE poll lookup, so that's fine.)
    poll_id = "test-poll-captcha"
    db_module.create_poll(poll_id, "match-x", "Chelsea vs Test", max_rating=10)

    r = client.post(
        "/api/vote_batch",
        headers={"X-Init-Data": init},
        json={"poll_id": poll_id, "votes": {"p1": 9, "p2": 7}},
    )
    assert r.status_code == 412
    body = r.get_json()
    assert body.get("captcha") is True
    assert body.get("error") == "captcha_required"


def test_first_vote_gate_passes_with_proof(client, make_init_data, db_module):
    """Same scenario, but with a freshly-minted X-Captcha-Proof header
    the request goes through (we'll see a 400/200 — anything but 412)."""
    import captcha as c
    init = make_init_data(user_id=88002)
    proof = c.issue_proof(88002)

    poll_id = "test-poll-captcha-2"
    db_module.create_poll(poll_id, "match-y", "Chelsea vs Test", max_rating=10)

    r = client.post(
        "/api/vote_batch",
        headers={"X-Init-Data": init, "X-Captcha-Proof": proof},
        json={"poll_id": poll_id, "votes": {"p1": 9, "p2": 7}},
    )
    # Could be 200 (success) or 400 (other validation) but NOT 412.
    assert r.status_code != 412


def test_first_vote_gate_rejects_proof_for_wrong_user(client, make_init_data):
    """A proof minted for user A presented on user B's request must NOT
    bypass the captcha — proofs are uid-bound."""
    import captcha as c
    init = make_init_data(user_id=88003)
    proof_for_other = c.issue_proof(99999)

    r = client.post(
        "/api/vote_batch",
        headers={"X-Init-Data": init, "X-Captcha-Proof": proof_for_other},
        json={"poll_id": "anything", "votes": {}},
    )
    assert r.status_code == 412
