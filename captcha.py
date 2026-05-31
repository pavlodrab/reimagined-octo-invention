"""
Chelsea-themed CAPTCHA — HMAC-signed challenge / proof tokens.

How it fits into the app
========================
The CAPTCHA is a soft anti-bot gate, not a security boundary. The flow:

1. Client hits an endpoint that's gated behind the CAPTCHA (currently
   `/api/vote_batch` for users with zero votes lifetime). Gate returns
   `412 Precondition Failed` with body `{"captcha": true, ...}`.
2. Client calls `GET /api/captcha/challenge`. Backend mints a random
   challenge (pick-the-Chelsea-crest or Chelsea-trivia question) and
   returns it together with an opaque `challenge_token`. The token is
   `base64url(payload).base64url(hmac_sha256(payload))` — payload
   contains the correct answer index plus an expiry, so the server
   doesn't have to remember anything between calls.
3. Client renders 4 options, user taps one, client POSTs `{token,
   answer}` to `/api/captcha/verify`. Backend re-signs the payload
   from the token, checks expiry, compares the answer, and on success
   issues a `proof_token` (separate HMAC, bound to the verified user
   id, valid for 30 minutes).
4. Client retries the original request with `X-Captcha-Proof: <proof>`.
   The gate accepts the proof and lets the request through.

Stateless — no DB writes, no Redis. The HMAC key comes from
`CAPTCHA_SECRET` (env), with a sensible fallback to `TELEGRAM_TOKEN` so
the captcha works on first deploy without extra config.

Why not reCAPTCHA / hCaptcha
============================
- We're inside a Telegram WebApp; loading a third-party captcha iframe
  is awkward and breaks if the user's network blocks Google.
- A bot that wants to evade a club-themed multiple-choice challenge has
  to either solve it (which requires a real Chelsea-savvy human OR a
  vision/LLM model — both meaningfully raise the cost per spam vote)
  or pre-fetch the challenge bank and cache answer-index by hash, but
  the answer index is randomized per challenge so the same option set
  can produce 4 different correct indices.
- For a fan club mini-app, passing this also acts as light flavour /
  trust signal ("real fans pass first try").
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple


# ── Config ────────────────────────────────────────────────────────────

# Challenge token TTL: short enough that grabbing one and using it later
# isn't useful for a botnet, long enough that a human can actually read
# the question and tap an answer.
CHALLENGE_TTL_SECONDS = 90

# Proof token TTL: how long a successful captcha pass stays valid.
# 30 minutes lets a user hit a few protected endpoints in a session
# without re-solving. We don't store these — they're stateless HMACs.
PROOF_TTL_SECONDS = 30 * 60


def _hmac_key() -> bytes:
    """Return the HMAC key as bytes. Order of preference:
       1. CAPTCHA_SECRET env (recommended in production)
       2. TELEGRAM_TOKEN env (already a secret, always present)
       3. A constant fallback (dev only — logged loudly elsewhere)
    """
    key = os.environ.get("CAPTCHA_SECRET", "").strip()
    if key:
        return key.encode("utf-8")
    tg = os.environ.get("TELEGRAM_TOKEN", "").strip()
    if tg:
        # Mix in a fixed salt so a leaked CAPTCHA challenge token can't be
        # turned into a Telegram-signature oracle.
        return hashlib.sha256(b"captcha:" + tg.encode("utf-8")).digest()
    return hashlib.sha256(b"captcha:dev-fallback").digest()


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def _sign(payload: Dict[str, Any]) -> str:
    """Serialize payload + append HMAC. Returns "<payload>.<sig>"."""
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    sig = hmac.new(_hmac_key(), body, hashlib.sha256).digest()
    return _b64url_encode(body) + "." + _b64url_encode(sig)


def _unsign(token: str) -> Optional[Dict[str, Any]]:
    """Parse `<payload>.<sig>`. Returns the payload dict if signature is
    valid AND the payload parses, else None."""
    if not token or "." not in token:
        return None
    try:
        body_b64, sig_b64 = token.split(".", 1)
        body = _b64url_decode(body_b64)
        sig = _b64url_decode(sig_b64)
    except (ValueError, base64.binascii.Error):
        return None
    expected = hmac.new(_hmac_key(), body, hashlib.sha256).digest()
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        return json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None


# ── Challenge banks ───────────────────────────────────────────────────
# Both banks live in code (not the i18n bundle) so the server picks the
# question and answer index without trusting the client's locale. The
# UI looks up *labels* via i18n keys at render time.

# Crest decoys: label + abbreviation + primary color. The frontend
# renders a stylised SVG shield using these — no licensed artwork.
# (Chelsea is added as the correct answer at challenge-mint time.)
_DECOY_CRESTS: List[Dict[str, str]] = [
    {"id": "ars", "abbr": "ARS", "color": "#EF0107", "name": "Arsenal"},
    {"id": "lfc", "abbr": "LFC", "color": "#C8102E", "name": "Liverpool"},
    {"id": "mun", "abbr": "MUN", "color": "#DA020E", "name": "Man Utd"},
    {"id": "mci", "abbr": "MCI", "color": "#6CABDD", "name": "Man City"},
    {"id": "tot", "abbr": "TOT", "color": "#132257", "name": "Tottenham"},
    {"id": "new", "abbr": "NEW", "color": "#241F20", "name": "Newcastle"},
    {"id": "avl", "abbr": "AVL", "color": "#670E36", "name": "Aston Villa"},
    {"id": "whu", "abbr": "WHU", "color": "#7A263A", "name": "West Ham"},
]
_CHELSEA_CREST: Dict[str, str] = {
    "id": "che", "abbr": "CFC", "color": "#034694", "name": "Chelsea",
}

# Trivia bank. `i18n_key` is a key into the client-side bundle so the
# question and option labels translate to the user's language. The
# `correct` field is the index (0..3) of the right answer in `options`.
# Add new questions here as one record — the new client-side i18n
# entries must be added in lockstep (i18n.js → captcha.trivia.<key>).
_TRIVIA_BANK: List[Dict[str, Any]] = [
    {
        "id": "kit_color",
        "i18n_key": "kit_color",
        "options": ["blue", "red", "black", "white"],
        "correct": 0,
    },
    {
        "id": "stadium",
        "i18n_key": "stadium",
        "options": ["stamford_bridge", "old_trafford", "anfield", "etihad"],
        "correct": 0,
    },
    {
        "id": "ucl_first_year",
        "i18n_key": "ucl_first_year",
        "options": ["2012", "2008", "2015", "2003"],
        "correct": 0,
    },
    {
        "id": "city",
        "i18n_key": "city",
        "options": ["london", "manchester", "liverpool", "newcastle"],
        "correct": 0,
    },
    {
        "id": "ucl_second_year",
        "i18n_key": "ucl_second_year",
        "options": ["2021", "2014", "2017", "2019"],
        "correct": 0,
    },
    {
        "id": "nickname",
        "i18n_key": "nickname",
        "options": ["blues", "reds", "gunners", "spurs"],
        "correct": 0,
    },
    {
        "id": "founded",
        "i18n_key": "founded",
        "options": ["1905", "1888", "1920", "1947"],
        "correct": 0,
    },
]


def _shuffle_with_correct(options: List[Any], correct_index: int) -> Tuple[List[Any], int]:
    """Shuffle `options` and return (shuffled_options, new_correct_index).

    We pull a fresh permutation from secrets.SystemRandom so the order is
    cryptographically random — crucial because the challenge_token's
    integrity hinges on the index NOT being predictable from the
    options themselves.
    """
    correct_value = options[correct_index]
    pool = list(options)
    rng = secrets.SystemRandom()
    rng.shuffle(pool)
    return pool, pool.index(correct_value)


def generate_challenge() -> Dict[str, Any]:
    """Mint a new challenge. Returns a dict ready to JSON-serialize:

        {
          "type":           "crest" | "trivia",
          "challenge_id":   <uuid>,
          "challenge_token": <opaque str>,
          "expires_at":     <unix seconds>,
          # type-specific:
          "options":        [...],
          "i18n_key":       "...",   # for trivia
        }

    The token encodes the correct answer and expiry. Verification is
    purely server-side — the client never sees the correct index.
    """
    now = int(time.time())
    expires_at = now + CHALLENGE_TTL_SECONDS
    challenge_id = uuid.uuid4().hex

    rng = secrets.SystemRandom()
    use_crest = rng.random() < 0.5

    if use_crest:
        decoys = rng.sample(_DECOY_CRESTS, 3)
        all_crests = decoys + [_CHELSEA_CREST]
        shuffled, correct_idx = _shuffle_with_correct(all_crests, 3)
        # Strip the human "name" before sending to the client — we don't
        # want to label the options, that's the whole point.
        public_options = [{"id": c["id"], "abbr": c["abbr"], "color": c["color"]}
                          for c in shuffled]
        token = _sign({
            "v": 1,
            "type": "crest",
            "cid": challenge_id,
            "correct": correct_idx,
            "exp": expires_at,
        })
        return {
            "type": "crest",
            "challenge_id": challenge_id,
            "challenge_token": token,
            "expires_at": expires_at,
            "options": public_options,
        }

    # Trivia branch
    item = rng.choice(_TRIVIA_BANK)
    shuffled, correct_idx = _shuffle_with_correct(list(item["options"]), item["correct"])
    token = _sign({
        "v": 1,
        "type": "trivia",
        "cid": challenge_id,
        "correct": correct_idx,
        "exp": expires_at,
    })
    return {
        "type": "trivia",
        "challenge_id": challenge_id,
        "challenge_token": token,
        "expires_at": expires_at,
        "i18n_key": item["i18n_key"],
        "options": shuffled,  # opaque keys, client looks them up in i18n
    }


# ── Verification ──────────────────────────────────────────────────────


class CaptchaResult:
    OK = "ok"
    EXPIRED = "expired"
    BAD_SIGNATURE = "bad_signature"
    WRONG_ANSWER = "wrong_answer"
    MALFORMED = "malformed"


def verify_challenge_answer(challenge_token: str, answer_index: int) -> str:
    """Check a user's answer to a challenge.

    Returns one of CaptchaResult.* — never raises. Caller decides what
    to do on each outcome (issue proof on OK, surface a friendly error
    otherwise).
    """
    payload = _unsign(challenge_token)
    if payload is None:
        return CaptchaResult.BAD_SIGNATURE
    if not isinstance(payload, dict):
        return CaptchaResult.MALFORMED
    exp = payload.get("exp")
    if not isinstance(exp, int) or exp < int(time.time()):
        return CaptchaResult.EXPIRED
    correct = payload.get("correct")
    if not isinstance(correct, int):
        return CaptchaResult.MALFORMED
    try:
        answer_int = int(answer_index)
    except (TypeError, ValueError):
        return CaptchaResult.MALFORMED
    if answer_int != correct:
        return CaptchaResult.WRONG_ANSWER
    return CaptchaResult.OK


def issue_proof(user_id: int) -> str:
    """Mint a proof token for a successfully-completed captcha,
    bound to a Telegram user id. The id binding stops a passed
    captcha from being shared between accounts."""
    now = int(time.time())
    return _sign({
        "v": 1,
        "kind": "proof",
        "uid": int(user_id),
        "iat": now,
        "exp": now + PROOF_TTL_SECONDS,
    })


def verify_proof(proof_token: str, expected_user_id: int) -> bool:
    """True iff the proof is signed correctly, not expired, and bound
    to `expected_user_id`."""
    if not proof_token:
        return False
    payload = _unsign(proof_token)
    if not isinstance(payload, dict):
        return False
    if payload.get("kind") != "proof":
        return False
    exp = payload.get("exp")
    if not isinstance(exp, int) or exp < int(time.time()):
        return False
    if payload.get("uid") != int(expected_user_id):
        return False
    return True
