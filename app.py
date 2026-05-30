"""
app.py  —  Flask backend for Chelsea Voting Mini App
"""
import os, json, time, uuid, hashlib, hmac, html, atexit, threading, queue, math
from urllib.parse import parse_qs

from flask import Flask, request, jsonify, send_from_directory, abort, g, has_request_context
from flask_cors import CORS
import requests as http_requests
from apscheduler.schedulers.background import BackgroundScheduler

from db import *

# ── Flask app ──────────────────────────────────────────────────────────
app = Flask(__name__, static_folder='miniapp', static_url_path='')
CORS(app)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
MINI_APP_URL   = os.getenv("MINI_APP_URL", "")
SSTATS_TOKEN   = os.getenv("SSTATS_TOKEN", "")
CHELSEA_ID     = 49  # sstats team ID

# DEMO_MODE controls whether unverified user identity (X-Demo-User header,
# ?user_id= query param) is accepted. Default OFF in production — only verified
# Telegram WebApp initData is trusted for authentication.
# For local browser-based development set DEMO_MODE=1.
DEMO_MODE = os.getenv("DEMO_MODE", "0").lower() in ("1", "true", "yes", "on")

# Maximum age of initData payload (seconds). Per Telegram docs the field
# auth_date should be checked to prevent replay attacks. 24h is a balance
# between UX (long-lived session) and risk window.
MAX_INIT_DATA_AGE_SECONDS = int(os.getenv("INIT_DATA_MAX_AGE", str(24 * 60 * 60)))

if not TELEGRAM_TOKEN and not DEMO_MODE:
    print("  ⚠️  TELEGRAM_TOKEN is empty and DEMO_MODE is off — all admin endpoints "
          "will reject every caller (no way to verify initData signatures).")
if DEMO_MODE:
    print("  ⚠️  DEMO_MODE=1 — X-Demo-User and ?user_id= identity fallbacks are accepted. "
          "MUST be off in production.")

init_db()


# ── Challenge System ───────────────────────────────────────────────────

def create_default_challenges():
    """Create standard challenges if none exist."""
    existing = get_active_challenges()
    if existing:
        return
    now = time.time()
    # Weekly: Vote in 3 consecutive polls
    create_challenge(
        title='Vote in 3 consecutive polls',
        description='Maintain a voting streak of 3 polls in a row',
        challenge_type='weekly',
        target=3,
        reward_xp=30,
        start_time=now,
        end_time=now + 7 * 86400
    )
    # Daily: Vote within 5 minutes of poll opening
    create_challenge(
        title='Quick voter',
        description='Vote within 5 minutes of a poll opening',
        challenge_type='daily',
        target=1,
        reward_xp=15,
        start_time=now,
        end_time=now + 86400
    )
    # Weekly: Rate your prediction in top-3
    create_challenge(
        title='Top-3 prediction',
        description='Have your prediction land in the top-3 rated players',
        challenge_type='weekly',
        target=1,
        reward_xp=25,
        start_time=now,
        end_time=now + 7 * 86400
    )


create_default_challenges()


def check_challenge_progress(user_id: int, event_type: str, context: dict = None):
    """Check all active challenges and update progress based on event."""
    if context is None:
        context = {}
    challenges = get_active_challenges()
    for ch in challenges:
        ch_id = ch['id']
        ch_type = (ch.get('type') or '').lower()

        if event_type == 'vote' and ch_type == 'weekly' and ch['target'] <= 10:
            # Weekly challenge with low target = consecutive vote challenge
            streak_val = context.get('streak', 0)
            if streak_val > 0:
                from db import get_connection as _gc
                conn = _gc()
                try:
                    row = conn.execute(
                        'SELECT progress, completed FROM challenge_progress WHERE user_id = ? AND challenge_id = ?',
                        (user_id, ch_id)
                    ).fetchone()
                    if row and row['completed']:
                        continue
                    # Set progress directly to streak value (not increment)
                    if row:
                        conn.execute(
                            'UPDATE challenge_progress SET progress = ? WHERE user_id = ? AND challenge_id = ?',
                            (streak_val, user_id, ch_id)
                        )
                    else:
                        conn.execute(
                            'INSERT INTO challenge_progress (user_id, challenge_id, progress) VALUES (?, ?, ?)',
                            (user_id, ch_id, streak_val)
                        )
                    conn.commit()
                finally:
                    conn.close()
                # Check completion
                if streak_val >= ch['target']:
                    complete_challenge(user_id, ch_id)

        elif event_type == 'quick_vote' and ch_type == 'daily':
            update_challenge_progress(user_id, ch_id, 1)
            # Check completion
            conn = get_connection()
            try:
                row = conn.execute(
                    'SELECT progress FROM challenge_progress WHERE user_id = ? AND challenge_id = ?',
                    (user_id, ch_id)
                ).fetchone()
                if row and row['progress'] >= ch['target']:
                    complete_challenge(user_id, ch_id)
            finally:
                conn.close()

        elif event_type == 'prediction_top3' and ch_type == 'weekly' and ch['target'] == 1:
            # Weekly challenge with target=1 that isn't the consecutive one
            # Only match if it's not a streak challenge (target <= 10 with streak context handled above)
            # This handles prediction challenges specifically
            from db import get_connection as _gc2
            conn2 = _gc2()
            try:
                row = conn2.execute(
                    'SELECT progress, completed FROM challenge_progress WHERE user_id = ? AND challenge_id = ?',
                    (user_id, ch_id)
                ).fetchone()
                if row and row['completed']:
                    continue
            finally:
                conn2.close()
            update_challenge_progress(user_id, ch_id, 1)
            conn = get_connection()
            try:
                row = conn.execute(
                    'SELECT progress FROM challenge_progress WHERE user_id = ? AND challenge_id = ?',
                    (user_id, ch_id)
                ).fetchone()
                if row and row['progress'] >= ch['target']:
                    complete_challenge(user_id, ch_id)
            finally:
                conn.close()


# ── SSE live updates ───────────────────────────────────────────────────

sse_clients = {}  # poll_id -> list of queue.Queue
SSE_MAX_PER_POLL = 50
SSE_MAX_TOTAL = 200


def _sse_total_connections():
    """Count total SSE connections across all polls."""
    return sum(len(clients) for clients in sse_clients.values())


def broadcast_sse(poll_id, event_type, data_dict):
    """Push an SSE event to all connected clients for a poll."""
    clients = sse_clients.get(poll_id, [])
    dead = []
    for q in clients:
        try:
            q.put_nowait((event_type, data_dict))
        except Exception:
            dead.append(q)
    for q in dead:
        try:
            clients.remove(q)
        except ValueError:
            pass


# ── Telegram notification helpers ──────────────────────────────────────

def send_telegram_message(chat_id, text, reply_markup=None):
    """Send a message via Telegram Bot API."""
    if not TELEGRAM_TOKEN or not chat_id:
        return None
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
    }
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    try:
        r = http_requests.post(url, json=payload, timeout=10)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


def send_poll_created_notification(poll_title):
    """Notify chat that a new poll was created."""
    cfg = get_config()
    if cfg.get('auto_notify') != '1':
        return
    chat_id = cfg.get('notify_chat_id', '')
    if not chat_id:
        return
    text = f"<b>New poll created!</b>\n{poll_title}\n\nVote now in the mini app."
    reply_markup = None
    if MINI_APP_URL:
        reply_markup = {
            "inline_keyboard": [[{
                "text": "Open Voting App",
                "web_app": {"url": MINI_APP_URL}
            }]]
        }
    send_telegram_message(chat_id, text, reply_markup)

    # Notify individual users with new_poll_notify enabled
    send_new_poll_notifications(poll_title)


def send_poll_closed_notification(poll_id):
    """Notify chat that a poll was closed with results summary."""
    cfg = get_config()
    if cfg.get('auto_notify') != '1':
        return
    chat_id = cfg.get('notify_chat_id', '')
    if not chat_id:
        return
    poll = get_poll(poll_id)
    if not poll:
        return
    results = get_results(poll_id)
    total_voters = get_total_votes_for_poll(poll_id)
    title = poll.get('title', 'Poll')
    text = f"<b>Poll closed:</b> {title}\n<b>Total voters:</b> {total_voters}\n\n"
    # Top 3 players
    conn = get_connection()
    try:
        for i, r in enumerate(results[:3], 1):
            player_row = conn.execute(
                'SELECT name FROM players WHERE player_id = ? AND match_id = ?',
                (r['player_id'], poll.get('match_id', ''))
            ).fetchone()
            name = player_row['name'] if player_row else r['player_id']
            text += f"{i}. {name} - {r['avg_rating']}\n"
    finally:
        conn.close()
    send_telegram_message(chat_id, text)

    # Notify individual users with results_notify enabled
    send_results_notifications(poll_id, title)


def send_notification_to_users(user_ids, text):
    """Send Telegram messages to a list of user IDs with rate limiting."""
    import time as _time
    for uid in user_ids:
        send_telegram_message(uid, text)
        _time.sleep(0.05)  # Rate limit: ~20 messages/second


def send_new_poll_notifications(poll_title):
    """Notify users who have new_poll_notify=1 about a new poll."""
    def _send():
        conn = get_connection()
        try:
            rows = conn.execute(
                'SELECT user_id FROM notification_prefs WHERE new_poll_notify = 1'
            ).fetchall()
            user_ids = [r['user_id'] for r in rows]
        finally:
            conn.close()
        if user_ids:
            text = f"New poll: <b>{poll_title}</b>\nRate the players now!"
            send_notification_to_users(user_ids, text)
    threading.Thread(target=_send, daemon=True).start()


def send_results_notifications(poll_id, poll_title):
    """Notify users who have results_notify=1 when results are ready."""
    def _send():
        conn = get_connection()
        try:
            rows = conn.execute(
                'SELECT user_id FROM notification_prefs WHERE results_notify = 1'
            ).fetchall()
            user_ids = [r['user_id'] for r in rows]
        finally:
            conn.close()
        if user_ids:
            text = f"Results are ready for <b>{poll_title}</b>! Check them out."
            send_notification_to_users(user_ids, text)
    threading.Thread(target=_send, daemon=True).start()


# ── Channel widget / Auto-post ─────────────────────────────────────────

def format_results_for_channel(poll_id, template='top5'):
    """Generate HTML-formatted text for Telegram channel post."""
    poll = get_poll(poll_id)
    if not poll:
        return ''
    results = get_results(poll_id)
    if not results:
        return ''
    total_voters = get_total_votes_for_poll(poll_id)
    title = poll.get('title', 'Match')
    match_id = poll.get('match_id', '')

    # Get player names
    conn = get_connection()
    try:
        player_names = {}
        for r in results:
            player_row = conn.execute(
                'SELECT name FROM players WHERE player_id = ? AND match_id = ?',
                (r['player_id'], match_id)
            ).fetchone()
            player_names[r['player_id']] = player_row['name'] if player_row else r['player_id']
    finally:
        conn.close()

    # Determine how many players to show
    if template == 'top3':
        scope = results[:3]
    elif template == 'top5':
        scope = results[:5]
    else:
        scope = results

    medal_emojis = ['\U0001f947', '\U0001f948', '\U0001f949']  # gold, silver, bronze

    lines = [f'<b>{title}</b>', '']
    for i, r in enumerate(scope):
        name = player_names.get(r['player_id'], r['player_id'])
        rank = i + 1
        medal = medal_emojis[i] if i < 3 else ''
        prefix = f"{medal} " if medal else f"{rank}. "
        lines.append(f"{prefix}{name} - {r['avg_rating']}")

    lines.append('')
    lines.append(f'<i>Total voters: {total_voters}</i>')
    return '\n'.join(lines)


def auto_post_results_to_channel(poll_id):
    """Post formatted results to the configured channel when a poll closes."""
    cfg = get_config()
    results_chat_id = cfg.get('results_chat_id', '')
    if not results_chat_id:
        return
    template = cfg.get('results_template', 'top5')
    text = format_results_for_channel(poll_id, template)
    if text:
        send_telegram_message(results_chat_id, text)


def generate_post_match_report(poll_id):
    """Generate and post a full match report after poll closes."""
    try:
        poll = get_poll(poll_id)
        if not poll:
            return
        match_id = poll.get('match_id', '')
        title = poll.get('title', 'Match')
        results = get_results(poll_id)
        if not results:
            return
        total_voters = get_total_votes_for_poll(poll_id)

        # Get player names
        conn = get_connection()
        try:
            player_names = {}
            for r in results:
                player_row = conn.execute(
                    'SELECT name FROM players WHERE player_id = ? AND match_id = ?',
                    (r['player_id'], match_id)
                ).fetchone()
                player_names[r['player_id']] = player_row['name'] if player_row else r['player_id']
        finally:
            conn.close()

        # Fan MVP (highest rated player)
        fan_mvp = results[0]
        fan_mvp_name = player_names.get(fan_mvp['player_id'], fan_mvp['player_id'])
        fan_mvp_rating = fan_mvp['avg_rating']

        # Top 3
        top3 = results[:3]
        top3_data = []
        for r in top3:
            top3_data.append({
                'player_id': r['player_id'],
                'name': player_names.get(r['player_id'], r['player_id']),
                'avg_rating': r['avg_rating']
            })

        # Most controversial (highest std_dev)
        controversial_players = _compute_controversial(poll_id)
        controversial = controversial_players[0] if controversial_players else None

        # AI ratings comparison
        ai_ratings = get_ai_ratings(match_id)
        ai_top3 = []
        ai_comparison = []
        if ai_ratings:
            ai_top3 = ai_ratings[:3]
            # Build a mapping of player_id -> ai normalized_rating
            ai_map = {r['player_id']: r.get('normalized_rating') or r.get('sstats_rating', 0) for r in ai_ratings}
            # Find biggest disagreements between fan and AI ratings
            for r in results[:10]:
                pid = r['player_id']
                if pid in ai_map and ai_map[pid]:
                    diff = round(r['avg_rating'] - ai_map[pid], 2)
                    if abs(diff) > 0.5:
                        ai_comparison.append({
                            'player_id': pid,
                            'name': player_names.get(pid, pid),
                            'fan_rating': r['avg_rating'],
                            'ai_rating': round(ai_map[pid], 2),
                            'difference': diff
                        })
            ai_comparison.sort(key=lambda x: abs(x['difference']), reverse=True)
            ai_comparison = ai_comparison[:5]

        # Build report data
        import datetime
        generated_at = time.time()
        report_data = {
            'fan_mvp': {'name': fan_mvp_name, 'rating': fan_mvp_rating},
            'top3': top3_data,
            'controversial': {
                'name': controversial['name'],
                'std_dev': controversial['std_dev'],
                'avg_rating': controversial['avg_rating']
            } if controversial else None,
            'total_voters': total_voters,
            'ai_comparison': ai_comparison,
            'ai_top3': [{'player_id': r['player_id'], 'name': player_names.get(r['player_id'], r['player_id']),
                         'rating': round(r.get('normalized_rating') or r.get('sstats_rating', 0), 2)} for r in ai_top3],
            'generated_at': generated_at
        }

        # Generate HTML report text for Telegram
        medal_emojis = ['\U0001f947', '\U0001f948', '\U0001f949']
        lines = []
        lines.append(f'\U0001f4cb <b>Match Report: {html.escape(title)}</b>')
        lines.append('')
        lines.append(f'\U0001f3c6 <b>Fan MVP:</b> {html.escape(fan_mvp_name)} - {fan_mvp_rating}')
        lines.append('')
        lines.append('<b>Top 3:</b>')
        for i, p in enumerate(top3_data):
            lines.append(f'{medal_emojis[i]} {html.escape(p["name"])} - {p["avg_rating"]}')
        lines.append('')
        if controversial:
            lines.append(f'\U0001f525 <b>Most Controversial:</b> {html.escape(controversial["name"])} (std: {controversial["std_dev"]:.2f})')
            lines.append('')
        lines.append(f'\U0001f465 <b>Total Voters:</b> {total_voters}')
        if ai_comparison:
            lines.append('')
            lines.append('\U0001f916 <b>AI vs Fans:</b>')
            for ac in ai_comparison[:3]:
                direction = '\u2191' if ac['difference'] > 0 else '\u2193'
                lines.append(f'  {direction} {html.escape(ac["name"])}: fans {ac["fan_rating"]} / AI {ac["ai_rating"]}')
        lines.append('')
        dt_str = datetime.datetime.fromtimestamp(generated_at).strftime('%d.%m.%Y %H:%M')
        lines.append(f'<i>Generated: {dt_str}</i>')

        report_text = '\n'.join(lines)

        # Save to DB
        save_match_report(poll_id, match_id, report_text, report_data)

        # Post to channel
        cfg = get_config()
        results_chat_id = cfg.get('results_chat_id', '')
        if results_chat_id:
            send_telegram_message(results_chat_id, report_text)
    except Exception as e:
        # Log the error and increment counter so failures are visible
        try:
            _increment_api_error_count()
            app.logger.error(f"generate_post_match_report failed: {e}")
        except Exception:
            pass


def announce_match_to_channel(poll_title, poll_id):
    """Send a pre-match announcement to the channel when a new poll is created."""
    cfg = get_config()
    results_chat_id = cfg.get('results_chat_id', '')
    announce = cfg.get('announce_matches', '1')
    if announce != '1' or not results_chat_id:
        return
    safe_title = html.escape(poll_title)
    text = f"New match voting: <b>{safe_title}</b>\nPredict the best player and rate the squad!"
    reply_markup = None
    if MINI_APP_URL:
        reply_markup = {
            "inline_keyboard": [[{
                "text": "Open Voting",
                "web_app": {"url": MINI_APP_URL}
            }]]
        }
    send_telegram_message(results_chat_id, text, reply_markup)


# ── Auto-close polls logic ─────────────────────────────────────────────

def check_auto_close_polls():
    """Close polls that have exceeded their voting period."""
    cfg = get_config()
    if cfg.get('auto_close_polls') != '1':
        return
    try:
        voting_hours = int(cfg.get('voting_period_hours', 24))
    except (ValueError, TypeError):
        voting_hours = 24
    now = time.time()
    open_polls = list_polls(status='open')
    for poll in open_polls:
        created_at = poll.get('created_at', 0)
        if created_at and (now - created_at) > voting_hours * 3600:
            poll_id = poll['poll_id']
            close_poll(poll_id)
            # Resolve predictions for this poll
            results = get_results(poll_id)
            if results:
                best_player_id = results[0]['player_id']
                resolve_predictions(poll_id, best_player_id)
                # Check prediction challenges for top-3 predictions
                top3_ids = [r['player_id'] for r in results[:3]]
                predictions = get_predictions_for_poll(poll_id)
                for pred in predictions:
                    if pred['player_id'] in top3_ids:
                        check_challenge_progress(pred['user_id'], 'prediction_top3', {})
            set_config('current_poll_id', '')
            send_poll_closed_notification(poll_id)
            auto_post_results_to_channel(poll_id)
            threading.Thread(target=generate_post_match_report, args=(poll_id,), daemon=True).start()


# ── Telegram initData verification ─────────────────────────────────────

def verify_init_data(init_data: str) -> dict | None:
    """Verify a Telegram WebApp initData payload and return the user dict.

    Implements the algorithm from
    https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app

    Returns:
        dict with the validated user fields (id, username, first_name, ...) on
        success, or None on any failure (bad signature, stale auth_date,
        malformed payload, missing token).
    """
    if not TELEGRAM_TOKEN or not init_data:
        return None

    # parse_qs URL-decodes values, which is what the spec requires for the
    # data-check-string. strict_parsing=True rejects malformed input.
    try:
        parsed = parse_qs(init_data, strict_parsing=True)
    except ValueError:
        return None

    received_hash = parsed.get('hash', [''])[0]
    if not received_hash:
        return None

    # Sort {key=value} pairs lexicographically by key, join with '\n'
    pairs = sorted(f"{k}={v[0]}" for k, v in parsed.items() if k != 'hash')
    data_check_string = '\n'.join(pairs)

    secret = hmac.new(b"WebAppData", TELEGRAM_TOKEN.encode(), hashlib.sha256).digest()
    expected_hash = hmac.new(secret, data_check_string.encode(), hashlib.sha256).hexdigest()

    # Constant-time comparison
    if not hmac.compare_digest(expected_hash, received_hash):
        return None

    # Freshness: auth_date must be within the allowed window.
    # This prevents replay of an intercepted initData.
    auth_date_str = parsed.get('auth_date', [''])[0]
    try:
        auth_date = int(auth_date_str)
    except (ValueError, TypeError):
        return None
    age = time.time() - auth_date
    if age < -60 or age > MAX_INIT_DATA_AGE_SECONDS:
        return None

    # Parse user payload — also enforce that it has a numeric id.
    user_str = parsed.get('user', [''])[0]
    if not user_str:
        return None
    try:
        user = json.loads(user_str)
    except (ValueError, TypeError):
        return None
    if not isinstance(user, dict) or not isinstance(user.get('id'), int):
        return None

    return user


def get_current_user_id() -> int | None:
    """Return the authenticated Telegram user_id, or None.

    Production (DEMO_MODE=0): only verified initData (X-Init-Data header) is
    accepted. Identity-claim headers / query params / body fields are ignored.

    Demo mode (DEMO_MODE=1): X-Demo-User header and ?user_id= query param
    are also accepted, in that order. Used for local browser dev only.
    """
    # Per-request cache: avoid HMAC-validating the same payload multiple times
    # within one request handler.
    if has_request_context() and 'cached_uid' in g:
        return g.cached_uid

    uid = None

    # 1) Trusted source: verified Telegram WebApp initData
    init_data = request.headers.get('X-Init-Data', '')
    if init_data:
        user = verify_init_data(init_data)
        if user:
            uid = int(user['id'])

    # 2) Demo-only identity fallbacks. NEVER trusted in production — these
    # let the caller name any user_id with no proof, so they must be gated
    # by an explicit DEMO_MODE flag.
    if uid is None and DEMO_MODE:
        demo_json = request.headers.get('X-Demo-User', '')
        if demo_json:
            try:
                claimed = int(json.loads(demo_json).get('id', 0))
                if claimed > 0:
                    uid = claimed
            except Exception:
                pass
        if uid is None:
            qp = request.args.get('user_id', type=int)
            if qp and qp > 0:
                uid = qp

    if has_request_context():
        g.cached_uid = uid
    return uid


def require_admin() -> int:
    uid = get_current_user_id()
    if not uid or not is_admin(uid):
        abort(403)
    return uid


# ── SStats API ─────────────────────────────────────────────────────────

SSTATS = "https://api.sstats.net"

def sstats(path, params=None):
    """Call sstats API (works without key, 300 req/min)."""
    headers = {"Authorization": f"Bearer {SSTATS_TOKEN}"} if SSTATS_TOKEN else {}
    try:
        r = http_requests.get(f"{SSTATS}{path}", headers=headers, params=params, timeout=10)
        if r.status_code == 200 and 'json' in r.headers.get('content-type', ''):
            d = r.json()
            if d.get('status') == 'OK':
                return d.get('data')
        # Non-200 or non-OK status: increment error counter
        _increment_api_error_count()
    except Exception:
        _increment_api_error_count()
    return None


def _increment_api_error_count():
    """Increment the API error counter in config."""
    try:
        cfg = get_config()
        count = int(cfg.get('api_error_count', '0'))
        set_config('api_error_count', str(count + 1))
    except Exception:
        pass


def get_chelsea_players_from_game(game_id: str) -> list:
    """Get Chelsea players who actually played in a specific match (starters + used subs)."""
    data = sstats(f"/Games/{game_id}")
    if not data:
        return []
    lineup = data.get('lineupPlayers', [])
    player_stats = data.get('playerStats', [])

    # Build set of player IDs that actually played (minutes is not None/null)
    played_ids = set()
    for ps in player_stats:
        if ps.get('minutes') is not None:
            played_ids.add(ps.get('playerId'))

    chelsea = [p for p in lineup if str(p.get('teamId')) == str(CHELSEA_ID)]
    result = []
    for p in chelsea:
        pid = p.get('playerId')
        # Only include players who actually played
        if pid not in played_ids:
            continue
        name = p.get('playerName', '')
        number = p.get('number', '')
        position = p.get('position', '')
        is_starter = p.get('startXI', False)
        photo_url = f"https://sstats.net/assets/player_photos/{pid}.png" if pid else ''
        result.append({
            'id': str(pid),
            'name': name,
            'number': str(number),
            'position': position,
            'is_starter': is_starter,
            'photo_url': photo_url,
        })
    # Sort: starters first, then subs
    result.sort(key=lambda x: (not x['is_starter'], x['name']))

    # Extract and store match events and AI ratings for Chelsea players
    if result:
        chelsea_player_ids = {p['id'] for p in result}
        max_rating = len(result) - 1

        # Extract events (goals, cards, substitutions) for Chelsea players
        events_raw = data.get('events', [])
        events_to_save = []
        for ev in events_raw:
            ev_player_id = str(ev.get('playerId', ''))
            if ev_player_id in chelsea_player_ids:
                event_type = ev.get('type')
                minute = ev.get('minute')
                # Build detail string from available fields
                detail = ev.get('detail', '') or ev.get('card', '') or ''
                if isinstance(detail, dict):
                    detail = json.dumps(detail)
                events_to_save.append({
                    'player_id': ev_player_id,
                    'event_type': event_type,
                    'minute': minute,
                    'detail': str(detail) if detail else '',
                })
        if events_to_save:
            save_match_events(game_id, events_to_save)

        # Extract ratings from playerStats for Chelsea players who played
        ratings_to_save = []
        for ps in player_stats:
            ps_player_id = str(ps.get('playerId', ''))
            if ps_player_id in chelsea_player_ids and ps.get('rating') is not None:
                sstats_rating = float(ps['rating'])
                # Normalize: (rating - 5.0) / (9.5 - 5.0) * max_rating
                normalized = (sstats_rating - 5.0) / (9.5 - 5.0) * max_rating
                normalized = max(0.0, min(float(max_rating), normalized))
                ratings_to_save.append({
                    'player_id': ps_player_id,
                    'sstats_rating': sstats_rating,
                    'normalized_rating': round(normalized, 2),
                })
        if ratings_to_save:
            save_ai_ratings(game_id, ratings_to_save)

    return result


def get_chelsea_squad() -> list:
    """Get Chelsea squad from /Teams/49 with photos (11 starters + 5 subs)."""
    data = sstats(f"/Teams/{CHELSEA_ID}")
    if not data:
        return []
    players = data.get('players', [])[:16]
    result = []
    for i, p in enumerate(players):
        pid = p.get('id')
        name = p.get('name', '')
        photo_url = f"https://sstats.net/assets/player_photos/{pid}.png" if pid else ''
        result.append({
            'id': str(pid),
            'name': name,
            'number': str(i + 1),
            'position': 'starter' if i < 11 else 'sub',
            'is_starter': i < 11,
            'photo_url': photo_url,
        })
    return result


# Default demo game — Sunderland vs Chelsea 2026-05-24 (last PL game of season)
DEMO_GAME_ID = "1379346"

def find_last_chelsea_game() -> dict | None:
    """Find the most recent completed Chelsea game, or use default demo game."""
    # Try using TeamId parameter directly
    games = sstats("/Games/list", {"TeamId": CHELSEA_ID, "limit": 50})
    if games:
        finished = [g for g in games if g.get('status') == 8]
        if finished:
            finished.sort(key=lambda x: x.get('dateUtc', ''), reverse=True)
            return finished[0]

    # Fallback: iterate years with LeagueId
    for year in [2025, 2024, 2023]:
        games = sstats("/Games/list", {"LeagueId": 39, "Year": year, "limit": 200})
        if games:
            chelsea = [g for g in games
                       if (g.get('homeTeam', {}).get('id') == CHELSEA_ID
                           or g.get('awayTeam', {}).get('id') == CHELSEA_ID)
                       and g.get('status') == 8]
            if chelsea:
                chelsea.sort(key=lambda x: x.get('dateUtc', ''), reverse=True)
                return chelsea[0]

    # Last resort: fallback to default demo game
    data = sstats(f"/Games/{DEMO_GAME_ID}")
    if data and data.get('game'):
        return data['game']
    return None


# ── Pre-match Analytics ─────────────────────────────────────────────────

def fetch_opponent_data(opponent_id):
    """Fetch opponent team info from sstats."""
    data = sstats(f"/Teams/{opponent_id}")
    if not data:
        return None
    return data


def fetch_h2h_stats(opponent_id):
    """Fetch head-to-head stats between Chelsea and the opponent."""
    games = sstats("/Games/list", {"TeamId": CHELSEA_ID, "limit": 100})
    if not games:
        return {'wins': 0, 'draws': 0, 'losses': 0, 'last_meetings': []}

    h2h_games = []
    for g in games:
        home_team = g.get('homeTeam', {})
        away_team = g.get('awayTeam', {})
        if home_team.get('id') == opponent_id or away_team.get('id') == opponent_id:
            if g.get('status') == 8:  # finished games only
                h2h_games.append(g)

    # Take last 5 meetings
    h2h_games = h2h_games[:5]

    wins = 0
    draws = 0
    losses = 0
    last_meetings = []

    for g in h2h_games:
        home_team = g.get('homeTeam', {})
        away_team = g.get('awayTeam', {})
        home_score = g.get('homeResult', 0) or 0
        away_score = g.get('awayResult', 0) or 0

        chelsea_is_home = home_team.get('id') == CHELSEA_ID
        if chelsea_is_home:
            chelsea_score = home_score
            opp_score = away_score
        else:
            chelsea_score = away_score
            opp_score = home_score

        if chelsea_score > opp_score:
            wins += 1
            result = 'W'
        elif chelsea_score < opp_score:
            losses += 1
            result = 'L'
        else:
            draws += 1
            result = 'D'

        last_meetings.append({
            'home': home_team.get('name', '?'),
            'away': away_team.get('name', '?'),
            'home_score': home_score,
            'away_score': away_score,
            'result': result
        })

    return {'wins': wins, 'draws': draws, 'losses': losses, 'last_meetings': last_meetings}


def generate_pre_match_analytics(game_id, poll_id):
    """Generate pre-match analytics for a game and post to channel."""
    try:
        # Get game data
        game_data = sstats(f"/Games/{game_id}")
        if not game_data:
            return
        game = game_data.get('game', game_data) if isinstance(game_data, dict) else None
        if not game:
            return

        home_team = game.get('homeTeam', {})
        away_team = game.get('awayTeam', {})

        # Determine opponent
        if home_team.get('id') == CHELSEA_ID:
            opponent_id = away_team.get('id')
            opponent_name = away_team.get('name', 'Unknown')
        else:
            opponent_id = home_team.get('id')
            opponent_name = home_team.get('name', 'Unknown')

        if not opponent_id:
            return

        # Fetch opponent data for form
        opponent_data = fetch_opponent_data(opponent_id)

        # Get opponent recent form (last 5 games)
        opp_games = sstats("/Games/list", {"TeamId": opponent_id, "limit": 20})
        opponent_form = []
        if opp_games:
            finished_games = [g for g in opp_games if g.get('status') == 8][:5]
            for g in finished_games:
                h_team = g.get('homeTeam', {})
                a_team = g.get('awayTeam', {})
                h_score = g.get('homeResult', 0) or 0
                a_score = g.get('awayResult', 0) or 0
                opp_is_home = h_team.get('id') == opponent_id
                if opp_is_home:
                    opp_score = h_score
                    other_score = a_score
                else:
                    opp_score = a_score
                    other_score = h_score
                if opp_score > other_score:
                    opponent_form.append('W')
                elif opp_score < other_score:
                    opponent_form.append('L')
                else:
                    opponent_form.append('D')

        # Fetch H2H stats
        h2h = fetch_h2h_stats(opponent_id)

        # Generate predicted result (simple heuristic)
        if h2h['wins'] > h2h['losses']:
            predicted_result = 'Chelsea Win'
        elif h2h['losses'] > h2h['wins']:
            predicted_result = 'Opponent Win'
        else:
            predicted_result = 'Draw'

        # Save analytics to DB
        analytics_data = {
            'opponent_name': opponent_name,
            'opponent_id': opponent_id,
            'opponent_form': opponent_form,
            'h2h_stats': h2h,
            'predicted_result': predicted_result,
            'analytics_data': {
                'opponent_team_data': opponent_data if isinstance(opponent_data, dict) else None
            }
        }
        save_match_analytics(str(game_id), poll_id, analytics_data)

        # Post pre-match summary to channel
        cfg = get_config()
        results_chat_id = cfg.get('results_chat_id', '')
        if results_chat_id:
            form_str = ' '.join(opponent_form) if opponent_form else 'N/A'
            h2h_str = f"W{h2h['wins']} D{h2h['draws']} L{h2h['losses']}"
            text = (
                f"<b>Pre-match Analytics</b>\n\n"
                f"<b>Opponent:</b> {html.escape(opponent_name)}\n"
                f"<b>Opponent Form:</b> {form_str}\n"
                f"<b>H2H (last 5):</b> {h2h_str}\n"
                f"<b>Prediction:</b> {predicted_result}"
            )
            send_telegram_message(results_chat_id, text)

    except Exception as e:
        # Log the error and increment counter so failures are visible
        try:
            _increment_api_error_count()
            app.logger.error(f"generate_pre_match_analytics failed: {e}")
        except Exception:
            pass


# ── Auto-create poll after Chelsea game ────────────────────────────────

def auto_create_poll_for_game(game: dict) -> str | None:
    """Create a poll for a Chelsea match with real lineup from /Games/{id}."""
    game_id = str(game.get('id', ''))
    home = game.get('homeTeam', {}).get('name', '?')
    away = game.get('awayTeam', {}).get('name', '?')

    # Include match score in title if available
    home_score = game.get('homeResult')
    away_score = game.get('awayResult')
    if home_score is not None and away_score is not None:
        title = f"{home} {home_score} - {away_score} {away}"
    else:
        title = f"{home} vs {away}"

    # Check if poll already exists
    existing = get_current_poll()
    if existing and existing.get('match_id') == game_id:
        return existing['poll_id']

    # Get real lineup from the game
    players = get_chelsea_players_from_game(game_id)
    if not players:
        # Fallback to squad
        players = get_chelsea_squad()
    if not players:
        return None

    max_rating = len(players) - 1  # 0..N-1 for unique ratings
    poll_id = f"match_{game_id}_{int(time.time())}"
    poll = create_poll(poll_id, game_id, title, max_rating)

    # Save players to DB
    conn = get_connection()
    try:
        # Clear old players for this match first
        conn.execute('DELETE FROM players WHERE match_id = ?', (game_id,))
        for p in players:
            conn.execute('''
                INSERT INTO players (player_id, match_id, name, number, position, photo_url, is_starter)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (p['id'], game_id, p['name'], p.get('number', ''),
                  p.get('position', ''), p.get('photo_url', ''), int(p.get('is_starter', False))))
        conn.commit()
    finally:
        conn.close()

    set_config("current_poll_id", poll_id)
    set_config("current_match_id", game_id)

    # Generate pre-match analytics in background thread
    try:
        threading.Thread(target=generate_pre_match_analytics, args=(game_id, poll_id), daemon=True).start()
    except Exception:
        pass

    return poll_id


def check_and_auto_create_poll():
    """Background task: create poll for Chelsea game if none exists for today."""
    cfg = get_config()
    if cfg.get('auto_create_polls') != '1':
        return
    # Don't auto-create if there's already a current poll
    existing = get_current_poll()
    if existing and existing.get('status') == 'open':
        return
    game = find_last_chelsea_game()
    if not game:
        return
    if game.get('status') == 8:
        poll_id = auto_create_poll_for_game(game)
        if poll_id:
            poll = get_poll(poll_id)
            if poll:
                send_poll_created_notification(poll.get('title', ''))
                announce_match_to_channel(poll.get('title', ''), poll_id)


# ── serve Mini App ─────────────────────────────────────────────────────

@app.route('/')
def index():
    return send_from_directory(app.static_folder, 'index.html')

@app.route('/<path:path>')
def static_files(path):
    return send_from_directory(app.static_folder, path)


# ═══════════════════════════════════════════════════════════════════════
#  PUBLIC API
# ═══════════════════════════════════════════════════════════════════════

@app.get("/api/config")
def api_config():
    cfg = get_config()
    return jsonify({
        "success": True,
        "config": {
            "voting_period_hours": int(cfg.get("voting_period_hours", 24)),
            "max_rating": int(cfg.get("max_rating", 15)),
            "current_match_id": cfg.get("current_match_id", ""),
            "current_poll_id": cfg.get("current_poll_id", ""),
            "bot_name": cfg.get("bot_name", "Chelsea Voting Bot"),
            "default_background_url": cfg.get("default_background_url", ""),
            "chelsea_team_id": CHELSEA_ID,
            "auto_close_polls": cfg.get("auto_close_polls", "1"),
            "auto_create_polls": cfg.get("auto_create_polls", "1"),
            "auto_notify": cfg.get("auto_notify", "1"),
            "allow_revote_hours": cfg.get("allow_revote_hours", "0"),
            "results_chat_id": cfg.get("results_chat_id", ""),
            "results_template": cfg.get("results_template", "top5"),
            "announce_matches": cfg.get("announce_matches", "1"),
        }
    })


@app.get("/api/chelsea/games")
def api_chelsea_games():
    """Find recent Chelsea games for admin to pick from."""
    games = []
    for year in [2024, 2025, 2023]:
        data = sstats("/Games/list", {"LeagueId": 39, "Year": year, "limit": 200})
        if data:
            for g in data:
                if g.get('homeTeam', {}).get('id') == CHELSEA_ID or g.get('awayTeam', {}).get('id') == CHELSEA_ID:
                    games.append({
                        'id': g['id'],
                        'home': g.get('homeTeam', {}).get('name', '?'),
                        'away': g.get('awayTeam', {}).get('name', '?'),
                        'date': g.get('date', '')[:10],
                        'status': g.get('statusName', ''),
                        'score': f"{g.get('homeResult', 0)}-{g.get('awayResult', 0)}",
                    })
    games.sort(key=lambda x: x.get('date', ''), reverse=True)
    return jsonify({"success": True, "games": games[:20]})


@app.get("/api/players")
def api_players():
    """Get Chelsea squad for current poll with real photos."""
    poll = get_current_poll()
    if not poll:
        return jsonify({"success": True, "players": [], "max_rating": 15})
    match_id = poll.get('match_id', '')
    conn = get_connection()
    try:
        rows = conn.execute('SELECT * FROM players WHERE match_id = ? ORDER BY number', (match_id,)).fetchall()
        players = [dict(r) for r in rows]
        # If no players in DB, fetch from sstats API
        if not players:
            players = get_chelsea_squad()
            for p in players:
                conn.execute('''
                    INSERT INTO players (player_id, match_id, name, number, position, photo_url, is_starter)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (p['id'], match_id, p['name'], p.get('number', ''), p.get('position', ''), p.get('photo_url', ''), int(p.get('is_starter', False))))
            conn.commit()
        # Convert is_starter to bool
        for p in players:
            p['is_starter'] = bool(p.get('is_starter', 0))
        return jsonify({"success": True, "players": players, "max_rating": poll.get('max_rating', len(players) - 1)})
    finally:
        conn.close()


def _get_events_by_player(match_id: str) -> dict:
    """Helper to get events grouped by player_id with emoji mapping."""
    events = get_match_events(match_id)
    events_by_player = {}
    for ev in events:
        event_type = ev.get('event_type')
        detail = ev.get('detail', '')
        if event_type == 1:
            emoji = "\u26bd"
        elif event_type == 2:
            if 'red' in str(detail).lower():
                emoji = "\U0001f7e5"
            else:
                emoji = "\U0001f7e8"
        elif event_type == 3:
            emoji = "\u21d4\ufe0f"
        else:
            emoji = ""
        pid = ev.get('player_id', '')
        if pid:
            if pid not in events_by_player:
                events_by_player[pid] = []
            events_by_player[pid].append({
                'type': event_type,
                'emoji': emoji,
                'minute': ev.get('minute'),
                'detail': detail,
            })
    return events_by_player


@app.get("/api/poll/current")
def api_current_poll():
    poll = get_current_poll()
    if not poll:
        return jsonify({"success": True, "poll": None, "results": [], "total_voters": 0, "players": []})
    results = get_results(poll["poll_id"])
    total_voters = get_total_votes_for_poll(poll["poll_id"])
    # Get user's vote
    uid = get_current_user_id()
    my_vote = None
    if uid:
        my_vote = get_user_vote(poll["poll_id"], uid)
    # Get players
    conn = get_connection()
    try:
        rows = conn.execute('SELECT * FROM players WHERE match_id = ? ORDER BY id', (poll['match_id'],)).fetchall()
        players = [dict(r) for r in rows]
        for p in players:
            p['is_starter'] = bool(p.get('is_starter', 0))
    finally:
        conn.close()
    return jsonify({
        "success": True,
        "poll": poll,
        "results": results,
        "total_voters": total_voters,
        "my_vote": my_vote,
        "players": players,
        "server_time": time.time(),
        "events": _get_events_by_player(poll.get('match_id', '')),
        "ai_ratings": get_ai_ratings(poll.get('match_id', '')),
    })


@app.post("/api/vote_batch")
def api_vote_batch():
    uid = get_current_user_id()
    if not uid:
        return jsonify({"success": False, "error": "unauthorized"}), 401

    body = request.get_json(force=True)
    poll_id = body.get("poll_id")
    votes = body.get("votes", {})  # {player_id: rating}
    batch_id = body.get("batch_id", str(uuid.uuid4()))

    poll = get_poll(poll_id)
    if not poll:
        return jsonify({"success": False, "error": "poll not found"}), 404
    if poll["status"] != "open":
        return jsonify({"success": False, "error": "poll closed"}), 400

    max_rating = poll.get("max_rating", 15)
    ratings = list(votes.values())

    if any(not (0 <= r <= max_rating) for r in ratings):
        return jsonify({"success": False, "error": f"ratings must be 0..{max_rating}"}), 400
    if len(set(ratings)) != len(ratings):
        return jsonify({"success": False, "error": "ratings must be unique"}), 400

    # Check if already voted
    if has_voted(poll_id, uid):
        return jsonify({"success": False, "error": "already voted"}), 400

    add_votes_batch(poll_id, uid, votes, batch_id)

    # XP and streak tracking
    get_or_create_profile(uid)
    add_xp(uid, 10, 'vote')
    update_streak(uid, poll_id)
    streak = get_user_streak(uid)
    if streak['current_streak'] > 1:
        add_xp(uid, min(5 * streak['current_streak'], 25), 'streak_bonus')

    # Challenge progress tracking
    check_challenge_progress(uid, 'vote', {'streak': streak['current_streak']})
    # Check quick vote (within 5 minutes of poll creation)
    if poll.get('created_at') and (time.time() - poll['created_at']) <= 300:
        check_challenge_progress(uid, 'quick_vote', {})

    # SSE broadcast
    profile = get_or_create_profile(uid)
    broadcast_sse(poll_id, 'vote_count', {
        'count': get_total_votes_for_poll(poll_id),
        'user': profile.get('first_name', '') or profile.get('username', 'Someone'),
    })

    return jsonify({"success": True})


@app.get("/api/stream/poll/<poll_id>")
def api_stream_poll(poll_id):
    """Server-Sent Events stream for live poll updates."""
    # Validate poll exists
    poll = get_poll(poll_id)
    if not poll:
        return jsonify({"success": False, "error": "poll not found"}), 404

    # Enforce connection limits
    if _sse_total_connections() >= SSE_MAX_TOTAL:
        return jsonify({"success": False, "error": "too many connections"}), 503
    poll_clients = sse_clients.get(poll_id, [])
    if len(poll_clients) >= SSE_MAX_PER_POLL:
        return jsonify({"success": False, "error": "too many connections for this poll"}), 503

    def generate():
        q = queue.Queue()
        if poll_id not in sse_clients:
            sse_clients[poll_id] = []
        sse_clients[poll_id].append(q)
        try:
            # Send initial connected event
            yield f"event: connected\ndata: {json.dumps({'poll_id': poll_id})}\n\n"
            # Send current vote count
            total = get_total_votes_for_poll(poll_id)
            yield f"event: vote_count\ndata: {json.dumps({'count': total})}\n\n"
            while True:
                try:
                    event_type, data = q.get(timeout=30)
                    yield f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
                except queue.Empty:
                    # Send keepalive comment
                    yield ": keepalive\n\n"
        except GeneratorExit:
            pass
        finally:
            try:
                sse_clients[poll_id].remove(q)
            except (ValueError, KeyError):
                pass

    from flask import Response
    return Response(
        generate(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no',
        }
    )


@app.get("/api/results/<poll_id>")
def api_results(poll_id):
    results = get_results(poll_id)
    total = get_total_votes_for_poll(poll_id)
    # Get detailed voter breakdown
    conn = get_connection()
    try:
        voters = conn.execute('''
            SELECT v.user_id, v.player_id, v.rating, p.username, p.first_name, p.custom_id, p.auto_id
            FROM votes v
            LEFT JOIN profiles p ON p.user_id = v.user_id
            WHERE v.poll_id = ?
            ORDER BY v.user_id, v.rating DESC
        ''', (poll_id,)).fetchall()
        voter_details = [dict(v) for v in voters]
    finally:
        conn.close()
    return jsonify({
        "success": True,
        "results": results,
        "total_voters": total,
        "voter_details": voter_details,
    })


@app.get("/api/results/<poll_id>/overrated")
def api_results_overrated(poll_id):
    """Compare community avg vs AI rating per player. Classify overrated/underrated."""
    poll = get_poll(poll_id)
    if not poll:
        return jsonify({"success": False, "error": "poll not found"}), 404
    match_id = poll.get('match_id', '')
    if not match_id:
        return jsonify({"success": True, "players": [], "no_data": True})

    community = get_results(poll_id)
    ai_ratings = get_ai_ratings(match_id)
    if not ai_ratings:
        return jsonify({"success": True, "players": [], "no_data": True})

    # Build lookup: player_id -> normalized_rating
    ai_map = {}
    for ar in ai_ratings:
        ai_map[str(ar['player_id'])] = ar.get('normalized_rating', 0)

    # Get player names
    conn = get_connection()
    try:
        rows = conn.execute('SELECT player_id, name FROM players WHERE match_id = ?', (match_id,)).fetchall()
        name_map = {str(r['player_id']): r['name'] for r in rows}
    finally:
        conn.close()

    players = []
    for cr in community:
        pid = str(cr['player_id'])
        if pid not in ai_map:
            continue
        community_avg = cr['avg_rating']
        ai_rating = ai_map[pid]
        diff = round(community_avg - ai_rating, 2)
        if diff > 1.5:
            classification = 'overrated'
        elif diff < -1.5:
            classification = 'underrated'
        else:
            classification = 'fair'
        players.append({
            'player_id': pid,
            'name': name_map.get(pid, pid),
            'community_avg': round(community_avg, 2),
            'ai_rating': round(ai_rating, 2),
            'difference': diff,
            'classification': classification,
        })

    # Sort by absolute difference descending
    players.sort(key=lambda x: abs(x['difference']), reverse=True)

    return jsonify({"success": True, "players": players, "no_data": False})


# ── FPL Integration ────────────────────────────────────────────────────

FPL_BASE = "https://fantasy.premierleague.com/api"


def fetch_fpl_bootstrap():
    """Fetch bootstrap-static from FPL API with 6-hour cache."""
    cached = get_fpl_cache('bootstrap_static')
    if cached and (time.time() - cached['cached_at'] < 6 * 3600):
        return cached['data']
    try:
        r = http_requests.get(f"{FPL_BASE}/bootstrap-static/", timeout=15)
        if r.status_code == 200:
            data = r.json()
            set_fpl_cache('bootstrap_static', data)
            return data
    except Exception:
        pass
    # Return stale cache if available
    if cached:
        return cached['data']
    return None


def get_chelsea_fpl_players():
    """Get all Chelsea players from FPL data."""
    data = fetch_fpl_bootstrap()
    if not data:
        return []
    teams = data.get('teams', [])
    chelsea_team_id = None
    for team in teams:
        if 'chelsea' in team.get('name', '').lower():
            chelsea_team_id = team.get('id')
            break
    if not chelsea_team_id:
        return []
    players = data.get('elements', [])
    chelsea_players = []
    for p in players:
        if p.get('team') == chelsea_team_id:
            chelsea_players.append({
                'id': p.get('id'),
                'web_name': p.get('web_name', ''),
                'first_name': p.get('first_name', ''),
                'second_name': p.get('second_name', ''),
                'total_points': p.get('total_points', 0),
                'event_points': p.get('event_points', 0),
            })
    return chelsea_players


def match_fpl_to_sstats(fpl_players, sstats_players):
    """Fuzzy match FPL players to sstats players. Returns dict: sstats_player_id -> fpl_points."""
    mapping = {}
    for sp in sstats_players:
        sp_name = (sp.get('name') or '').strip().lower()
        sp_id = str(sp.get('player_id') or sp.get('id', ''))
        if not sp_name:
            continue
        sp_last = sp_name.split()[-1] if sp_name else ''
        best_match = None
        for fp in fpl_players:
            fp_web = (fp.get('web_name') or '').strip().lower()
            fp_second = (fp.get('second_name') or '').strip().lower()
            fp_full = f"{(fp.get('first_name') or '').strip().lower()} {fp_second}"
            # Exact full match
            if sp_name == fp_full or sp_name == fp_web or sp_name == fp_second:
                best_match = fp
                break
            # Last name match
            if sp_last and (sp_last == fp_web or sp_last == fp_second):
                best_match = fp
                break
            # Partial: last name contained in web_name or vice versa
            if sp_last and len(sp_last) > 1 and (sp_last in fp_web or fp_web in sp_last):
                best_match = fp
                break
        if best_match:
            mapping[sp_id] = {
                'fpl_points': best_match.get('total_points', 0),
                'event_points': best_match.get('event_points', 0),
                'fpl_player_id': best_match.get('id'),
                'web_name': best_match.get('web_name', ''),
            }
    return mapping


@app.get("/api/analytics/<poll_id>")
def api_analytics(poll_id):
    """Return pre-match analytics data for a poll."""
    analytics = get_analytics_by_poll(poll_id)
    if not analytics:
        return jsonify({"success": False, "error": "No analytics available"})
    return jsonify({
        "success": True,
        "analytics": {
            "opponent_name": analytics.get('opponent_name'),
            "opponent_id": analytics.get('opponent_id'),
            "opponent_form": analytics.get('opponent_form'),
            "h2h_stats": analytics.get('h2h_stats'),
            "predicted_result": analytics.get('predicted_result'),
            "generated_at": analytics.get('generated_at')
        }
    })


@app.get("/api/report/<poll_id>")
def api_report(poll_id):
    """Return the post-match report for a poll."""
    report = get_match_report(poll_id)
    if not report:
        return jsonify({"success": False, "error": "Report not available"})
    return jsonify({
        "success": True,
        "report_text": report.get('report_text', ''),
        "report_data": report.get('report_data'),
        "generated_at": report.get('generated_at')
    })


@app.get("/api/fpl/gameweek")
def api_fpl_gameweek():
    """Return current GW info and Chelsea FPL player data (cached 1 hour)."""
    cached = get_fpl_cache('fpl_gameweek_response')
    if cached and (time.time() - cached['cached_at'] < 3600):
        return jsonify({"success": True, **cached['data']})

    data = fetch_fpl_bootstrap()
    if not data:
        return jsonify({"success": False, "error": "FPL data not available"})

    # Find current gameweek
    events = data.get('events', [])
    current_gw = None
    for ev in events:
        if ev.get('is_current'):
            current_gw = ev.get('id')
            break
    if not current_gw and events:
        # Fallback: last finished event
        for ev in reversed(events):
            if ev.get('finished'):
                current_gw = ev.get('id')
                break

    chelsea_players = get_chelsea_fpl_players()

    # Get sstats players for current poll (for mapping)
    cfg = get_config()
    match_id = cfg.get('current_match_id', '')
    sstats_players = []
    if match_id:
        conn = get_connection()
        try:
            rows = conn.execute('SELECT player_id, name FROM players WHERE match_id = ?', (match_id,)).fetchall()
            sstats_players = [dict(r) for r in rows]
        finally:
            conn.close()

    mapping = match_fpl_to_sstats(chelsea_players, sstats_players) if sstats_players else {}

    response_data = {
        'gameweek': current_gw,
        'players': chelsea_players,
        'mapping': mapping,
    }
    set_fpl_cache('fpl_gameweek_response', response_data)
    return jsonify({"success": True, **response_data})


@app.get("/api/fpl/correlation/<poll_id>")
def api_fpl_correlation(poll_id):
    """Compute Pearson correlation between community ratings and FPL points."""
    poll = get_poll(poll_id)
    if not poll:
        return jsonify({"success": False, "error": "poll not found"}), 404

    match_id = poll.get('match_id', '')
    community = get_results(poll_id)
    if not community:
        return jsonify({"success": True, "correlation": None, "players": [], "no_data": True})

    # Get sstats players for the match
    conn = get_connection()
    try:
        rows = conn.execute('SELECT player_id, name FROM players WHERE match_id = ?', (match_id,)).fetchall()
        sstats_players = [dict(r) for r in rows]
    finally:
        conn.close()

    if not sstats_players:
        return jsonify({"success": True, "correlation": None, "players": [], "no_data": True})

    chelsea_fpl = get_chelsea_fpl_players()
    if not chelsea_fpl:
        return jsonify({"success": True, "correlation": None, "players": [], "no_data": True})

    mapping = match_fpl_to_sstats(chelsea_fpl, sstats_players)

    # Build paired data: community rating + FPL points
    pairs = []
    player_comparison = []
    for cr in community:
        pid = str(cr['player_id'])
        if pid in mapping:
            fpl_pts = mapping[pid]['event_points']
            pairs.append((cr['avg_rating'], fpl_pts))
            # Get player name
            name = pid
            for sp in sstats_players:
                if str(sp.get('player_id')) == pid:
                    name = sp.get('name', pid)
                    break
            player_comparison.append({
                'player_id': pid,
                'name': name,
                'community_rating': round(cr['avg_rating'], 2),
                'fpl_points': fpl_pts,
                'web_name': mapping[pid].get('web_name', ''),
            })

    if len(pairs) < 3:
        return jsonify({"success": True, "correlation": None, "players": player_comparison, "no_data": True})

    # Compute Pearson correlation
    n = len(pairs)
    sum_x = sum(p[0] for p in pairs)
    sum_y = sum(p[1] for p in pairs)
    sum_xy = sum(p[0] * p[1] for p in pairs)
    sum_x2 = sum(p[0] ** 2 for p in pairs)
    sum_y2 = sum(p[1] ** 2 for p in pairs)

    numerator = n * sum_xy - sum_x * sum_y
    denominator = math.sqrt((n * sum_x2 - sum_x ** 2) * (n * sum_y2 - sum_y ** 2))

    if denominator == 0:
        correlation = 0.0
    else:
        correlation = round(numerator / denominator, 3)

    return jsonify({
        "success": True,
        "correlation": correlation,
        "players": player_comparison,
        "no_data": False,
    })


@app.get("/api/profile/<int:uid>")
def api_profile(uid):
    prof = get_profile(uid)
    if not prof:
        return jsonify({"success": False, "error": "not found"}), 404
    stats = get_profile_stats(uid)
    xp_data = get_user_xp(uid)
    streak_data = get_user_streak(uid)
    awards = get_user_awards(uid)
    return jsonify({"success": True, "profile": {**prof, **stats, "xp_data": xp_data, "streak_data": streak_data, "awards": awards}})


@app.get("/api/profile/me")
def api_profile_me():
    uid = get_current_user_id()
    if not uid:
        return jsonify({"success": False, "error": "unauthorized"}), 401
    return api_profile(uid)


@app.post("/api/profile/update")
def api_profile_update():
    uid = get_current_user_id()
    if not uid:
        return jsonify({"success": False, "error": "unauthorized"}), 401
    body = request.get_json(force=True)
    # Check custom_id uniqueness
    if 'custom_id' in body:
        conn = get_connection()
        try:
            existing = conn.execute('SELECT user_id FROM profiles WHERE custom_id = ? AND user_id != ?',
                                    (body['custom_id'], uid)).fetchone()
            if existing:
                return jsonify({"success": False, "error": "custom_id already taken"}), 400
        finally:
            conn.close()
    update_profile(uid, **body)
    return jsonify({"success": True})


@app.get("/api/backgrounds")
def api_backgrounds():
    return jsonify({"success": True, "backgrounds": list_backgrounds()})


@app.get("/api/health")
def health():
    return jsonify({
        "ok": True,
        "ts": time.time(),
    })


# ═══════════════════════════════════════════════════════════════════════
#  NEW FEATURE API ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════

@app.get("/api/leaderboard")
def api_leaderboard():
    """Voter leaderboard with badges and consistency scores."""
    leaders = get_voter_leaderboard()
    cfg = get_config()
    max_rating = int(cfg.get('max_rating', 10))

    # Calculate per-poll averages for consistency scoring
    conn = get_connection()
    try:
        # Get all poll averages per user
        user_poll_avgs = {}
        poll_global_avgs = {}

        # Global avg per poll
        poll_avgs_rows = conn.execute('''
            SELECT poll_id, AVG(rating) as poll_avg
            FROM votes GROUP BY poll_id
        ''').fetchall()
        for r in poll_avgs_rows:
            poll_global_avgs[r['poll_id']] = r['poll_avg']

        # Per-user avg per poll
        user_avgs_rows = conn.execute('''
            SELECT user_id, poll_id, AVG(rating) as user_avg
            FROM votes GROUP BY user_id, poll_id
        ''').fetchall()
        for r in user_avgs_rows:
            uid = r['user_id']
            if uid not in user_poll_avgs:
                user_poll_avgs[uid] = []
            global_avg = poll_global_avgs.get(r['poll_id'], 0)
            user_poll_avgs[uid].append(abs(r['user_avg'] - global_avg))
    finally:
        conn.close()

    result = []
    for leader in leaders:
        uid = leader['user_id']
        deviations = user_poll_avgs.get(uid, [])
        if deviations and max_rating > 0:
            avg_deviation = sum(deviations) / len(deviations)
            consistency_score = 1 - (avg_deviation / max_rating)
            consistency_score = max(0.0, min(1.0, consistency_score))
        else:
            consistency_score = 0.5

        badges = []
        total = leader.get('total_votes', 0)
        if total >= 50:
            badges.append('veteran')
        if total >= 20:
            badges.append('active')
        if consistency_score >= 0.7:
            badges.append('seer')
        if consistency_score <= 0.3:
            badges.append('rebel')

        leader['consistency_score'] = round(consistency_score, 3)
        leader['badges'] = badges
        result.append(leader)

    return jsonify({"success": True, "leaderboard": result})


@app.get("/api/season-stats")
def api_season_stats():
    """Player season averages, form curves, and Team of the Season."""
    stats = get_season_stats(limit=50)

    # Calculate form curves (last 5 and last 10 match ratings)
    for player in stats:
        history = get_player_history(player['player_id'])
        ratings = [h['avg_rating'] for h in history]
        player['form_last_5'] = ratings[:5]
        player['form_last_10'] = ratings[:10]

    # Team of the Season: top 11 by avg rating
    team_of_season = stats[:11] if len(stats) >= 11 else stats[:]

    return jsonify({
        "success": True,
        "stats": stats,
        "team_of_season": team_of_season,
    })


@app.get("/api/match-history")
def api_match_history():
    """All closed polls with results summary."""
    closed_polls = list_polls(status='closed', limit=100)
    history = []
    conn = get_connection()
    try:
        for poll in closed_polls:
            poll_id = poll['poll_id']
            match_id = poll.get('match_id', '')
            # Use a single query with JOIN to get top 3 players with names
            top3_rows = conn.execute('''
                SELECT v.player_id, ROUND(AVG(v.rating), 2) as avg_rating, pl.name
                FROM votes v
                LEFT JOIN players pl ON pl.player_id = v.player_id AND pl.match_id = ?
                WHERE v.poll_id = ?
                GROUP BY v.player_id
                ORDER BY avg_rating DESC
                LIMIT 3
            ''', (match_id, poll_id)).fetchall()
            total_voters = conn.execute(
                'SELECT COUNT(DISTINCT user_id) as c FROM votes WHERE poll_id = ?', (poll_id,)
            ).fetchone()['c']
            top3 = []
            for r in top3_rows:
                top3.append({
                    'player_id': r['player_id'],
                    'name': r['name'] if r['name'] else r['player_id'],
                    'avg_rating': r['avg_rating'],
                })
            history.append({
                'poll_id': poll_id,
                'title': poll.get('title', ''),
                'match_id': match_id,
                'created_at': poll.get('created_at'),
                'closed_at': poll.get('closed_at'),
                'total_voters': total_voters,
                'top3': top3,
            })
    finally:
        conn.close()
    return jsonify({"success": True, "history": history})


@app.get("/api/player/<player_id>/history")
def api_player_history(player_id):
    """Match-by-match ratings for a player."""
    history = get_player_history(player_id)
    return jsonify({"success": True, "history": history})


@app.post("/api/prediction")
def api_submit_prediction():
    """Submit a pre-match best player prediction."""
    uid = get_current_user_id()
    if not uid:
        return jsonify({"success": False, "error": "unauthorized"}), 401
    body = request.get_json(force=True)
    poll_id = body.get('poll_id', '')
    player_id = body.get('player_id', '')
    if not poll_id or not player_id:
        return jsonify({"success": False, "error": "missing poll_id or player_id"}), 400
    # Check poll is open
    poll = get_poll(poll_id)
    if not poll:
        return jsonify({"success": False, "error": "poll not found"}), 404
    if poll['status'] != 'open':
        return jsonify({"success": False, "error": "poll is closed"}), 400
    add_prediction(poll_id, uid, player_id)
    return jsonify({"success": True})


@app.get("/api/prediction/<poll_id>")
def api_get_prediction(poll_id):
    """Get user's prediction for a poll."""
    uid = get_current_user_id()
    if not uid:
        return jsonify({"success": False, "error": "unauthorized"}), 401
    pred = get_prediction(poll_id, uid)
    return jsonify({"success": True, "prediction": pred})


@app.get("/api/predictions/results")
def api_prediction_results():
    """Prediction leaderboard with points."""
    conn = get_connection()
    try:
        rows = conn.execute('''
            SELECT pr.user_id, p.username, p.first_name, p.custom_id, p.auto_id,
                   SUM(pr.points_earned) as total_points,
                   COUNT(pr.id) as total_predictions,
                   SUM(CASE WHEN pr.points_earned = 10 THEN 1 ELSE 0 END) as exact_matches
            FROM prediction_results pr
            LEFT JOIN profiles p ON p.user_id = pr.user_id
            GROUP BY pr.user_id
            ORDER BY total_points DESC
            LIMIT 50
        ''').fetchall()
        results = [dict(r) for r in rows]
    finally:
        conn.close()
    return jsonify({"success": True, "results": results})


@app.post("/api/mini-game/guess")
def api_mini_game_guess():
    """Submit a mini-game guess (lineup or score)."""
    uid = get_current_user_id()
    if not uid:
        return jsonify({"success": False, "error": "unauthorized"}), 401
    body = request.get_json(force=True)
    match_id = body.get('match_id', '')
    game_type = body.get('game_type', '')
    guess = body.get('guess', '')
    if not match_id or not game_type or not guess:
        return jsonify({"success": False, "error": "missing fields"}), 400
    if game_type not in ('lineup', 'score'):
        return jsonify({"success": False, "error": "game_type must be 'lineup' or 'score'"}), 400
    guess_json = json.dumps(guess) if not isinstance(guess, str) else guess
    add_mini_game_guess(match_id, uid, game_type, guess_json)
    return jsonify({"success": True})


@app.get("/api/mini-game/results/<match_id>")
def api_mini_game_results(match_id):
    """Get mini-game results for a match."""
    uid = get_current_user_id()
    results = get_mini_game_results(match_id, user_id=uid)
    all_results = get_mini_game_results(match_id)
    return jsonify({"success": True, "my_results": results, "all_results": all_results})


@app.post("/api/revote")
def api_revote():
    """Allow re-voting within the allowed hours window."""
    uid = get_current_user_id()
    if not uid:
        return jsonify({"success": False, "error": "unauthorized"}), 401
    body = request.get_json(force=True)
    poll_id = body.get('poll_id', '')
    if not poll_id:
        return jsonify({"success": False, "error": "missing poll_id"}), 400

    cfg = get_config()
    allow_hours = float(cfg.get('allow_revote_hours', '0'))
    if allow_hours <= 0:
        return jsonify({"success": False, "error": "re-voting is disabled"}), 400

    poll = get_poll(poll_id)
    if not poll:
        return jsonify({"success": False, "error": "poll not found"}), 404
    if poll['status'] != 'open':
        return jsonify({"success": False, "error": "poll is closed"}), 400

    # Check time window: user can only revote within allow_revote_hours of poll creation
    now = time.time()
    poll_created = poll.get('created_at', 0)
    if (now - poll_created) > allow_hours * 3600:
        return jsonify({"success": False, "error": "revote window has expired"}), 400

    # Check user has actually voted before
    if not has_voted(poll_id, uid):
        return jsonify({"success": False, "error": "you have not voted yet"}), 400

    delete_user_votes(poll_id, uid)
    return jsonify({"success": True, "message": "votes deleted, you can vote again"})


@app.post("/api/admin/reset-vote")
def api_admin_reset_vote():
    """Admin resets a user's vote to allow re-vote."""
    admin_id = _admin_check()
    body = request.get_json(force=True)
    poll_id = body.get('poll_id', '')
    target_uid = int(body.get('user_id', 0))
    if not poll_id or target_uid <= 0:
        return jsonify({"success": False, "error": "missing fields"}), 400
    delete_user_votes(poll_id, target_uid)
    add_log(admin_id, "reset_vote", target_user_id=target_uid, details={"poll_id": poll_id})
    return jsonify({"success": True})


@app.get("/api/notifications/prefs")
def api_get_notification_prefs():
    """Get notification preferences for current user."""
    uid = get_current_user_id()
    if not uid:
        return jsonify({"success": False, "error": "unauthorized"}), 401
    prefs = get_notification_prefs(uid)
    return jsonify({"success": True, "prefs": prefs})


@app.post("/api/notifications/prefs")
def api_set_notification_prefs():
    """Update notification preferences."""
    uid = get_current_user_id()
    if not uid:
        return jsonify({"success": False, "error": "unauthorized"}), 401
    body = request.get_json(force=True)
    # Validate that all values are integers (0 or 1)
    allowed_keys = {'remind_before_close', 'new_poll_notify', 'results_notify'}
    validated = {}
    for k, v in body.items():
        if k not in allowed_keys:
            continue
        try:
            int_val = int(v)
            if int_val not in (0, 1):
                return jsonify({"success": False, "error": f"'{k}' must be 0 or 1"}), 400
            validated[k] = int_val
        except (ValueError, TypeError):
            return jsonify({"success": False, "error": f"'{k}' must be an integer (0 or 1)"}), 400
    if not validated:
        return jsonify({"success": False, "error": "no valid preference fields provided"}), 400
    set_notification_prefs(uid, **validated)
    prefs = get_notification_prefs(uid)
    return jsonify({"success": True, "prefs": prefs})


@app.post("/api/referral")
def api_referral():
    """Register a referral."""
    uid = get_current_user_id()
    if not uid:
        return jsonify({"success": False, "error": "unauthorized"}), 401
    body = request.get_json(force=True)
    referrer_code = body.get('referrer_code', '')
    if not referrer_code:
        return jsonify({"success": False, "error": "missing referrer_code"}), 400
    # Resolve referrer_code to a user_id (could be custom_id or auto_id)
    conn = get_connection()
    try:
        referrer = conn.execute(
            'SELECT user_id FROM profiles WHERE custom_id = ? OR auto_id = ?',
            (referrer_code, referrer_code)
        ).fetchone()
    finally:
        conn.close()
    if not referrer:
        return jsonify({"success": False, "error": "referrer not found"}), 404
    referrer_id = referrer['user_id']
    if referrer_id == uid:
        return jsonify({"success": False, "error": "cannot refer yourself"}), 400
    add_referral(referrer_id, uid)
    add_xp(referrer_id, 30, 'referral')
    return jsonify({"success": True, "referrer_id": referrer_id})


@app.get("/api/xp/me")
def api_xp_me():
    """Get current user's XP, level, streak, and unlocked avatars."""
    uid = get_current_user_id()
    if not uid:
        return jsonify({"success": False, "error": "unauthorized"}), 401
    xp_data = get_user_xp(uid)
    streak_data = get_user_streak(uid)
    # Determine unlocked avatars based on level
    level = xp_data['level']
    unlocked_avatars = list(range(5))  # 0-4 always unlocked
    if level in ('Фанат', 'Ультрас', 'Легенда Стэмфорд Бридж'):
        unlocked_avatars += [5, 6]
    if level in ('Ультрас', 'Легенда Стэмфорд Бридж'):
        unlocked_avatars += [7, 8]
    if level == 'Легенда Стэмфорд Бридж':
        unlocked_avatars += [9]
    return jsonify({
        "success": True,
        "xp": xp_data,
        "streak": streak_data,
        "unlocked_avatars": unlocked_avatars,
    })


@app.get("/api/xp/<int:uid>")
def api_xp_user(uid):
    """Get any user's XP, level, streak, and unlocked avatars."""
    xp_data = get_user_xp(uid)
    streak_data = get_user_streak(uid)
    level = xp_data['level']
    unlocked_avatars = list(range(5))
    if level in ('Фанат', 'Ультрас', 'Легенда Стэмфорд Бридж'):
        unlocked_avatars += [5, 6]
    if level in ('Ультрас', 'Легенда Стэмфорд Бридж'):
        unlocked_avatars += [7, 8]
    if level == 'Легенда Стэмфорд Бридж':
        unlocked_avatars += [9]
    return jsonify({
        "success": True,
        "xp": xp_data,
        "streak": streak_data,
        "unlocked_avatars": unlocked_avatars,
    })


@app.get("/api/compare/<int:uid1>/<int:uid2>")
def api_compare_users(uid1, uid2):
    """Compare voting similarity between two users."""
    # Require that the current user is one of the two UIDs being compared (or is admin)
    current_uid = get_current_user_id()
    if not current_uid:
        return jsonify({"success": False, "error": "unauthorized"}), 401
    if current_uid != uid1 and current_uid != uid2 and not is_admin(current_uid):
        return jsonify({"success": False, "error": "forbidden"}), 403

    conn = get_connection()
    try:
        # Get polls where both users voted
        common_polls = conn.execute('''
            SELECT DISTINCT v1.poll_id
            FROM votes v1
            JOIN votes v2 ON v2.poll_id = v1.poll_id AND v2.user_id = ?
            WHERE v1.user_id = ?
        ''', (uid2, uid1)).fetchall()
        common_poll_ids = [r['poll_id'] for r in common_polls]

        if not common_poll_ids:
            return jsonify({
                "success": True,
                "common_polls": 0,
                "similarity": 0,
                "details": [],
            })

        total_diff = 0
        total_comparisons = 0
        details = []

        for poll_id in common_poll_ids:
            votes1 = conn.execute(
                'SELECT player_id, rating FROM votes WHERE poll_id = ? AND user_id = ?',
                (poll_id, uid1)
            ).fetchall()
            votes2 = conn.execute(
                'SELECT player_id, rating FROM votes WHERE poll_id = ? AND user_id = ?',
                (poll_id, uid2)
            ).fetchall()
            v1_map = {r['player_id']: r['rating'] for r in votes1}
            v2_map = {r['player_id']: r['rating'] for r in votes2}

            common_players = set(v1_map.keys()) & set(v2_map.keys())
            poll_diff = 0
            for pid in common_players:
                diff = abs(v1_map[pid] - v2_map[pid])
                poll_diff += diff
                total_diff += diff
                total_comparisons += 1

            if common_players:
                poll = get_poll(poll_id)
                details.append({
                    'poll_id': poll_id,
                    'title': poll.get('title', '') if poll else '',
                    'avg_diff': round(poll_diff / len(common_players), 2),
                })
    finally:
        conn.close()

    cfg = get_config()
    max_rating = int(cfg.get('max_rating', 10))
    if total_comparisons > 0 and max_rating > 0:
        avg_diff = total_diff / total_comparisons
        similarity = round(1 - (avg_diff / max_rating), 3)
        similarity = max(0.0, min(1.0, similarity))
    else:
        similarity = 0

    return jsonify({
        "success": True,
        "common_polls": len(common_poll_ids),
        "similarity": similarity,
        "total_comparisons": total_comparisons,
        "details": details,
    })


@app.get("/api/results/<poll_id>/visualization")
def api_results_visualization(poll_id):
    """Enhanced results with bar chart data, medals, and best/worst match stats."""
    poll = get_poll(poll_id)
    if not poll:
        return jsonify({"success": False, "error": "poll not found"}), 404
    results = get_results(poll_id)
    total_voters = get_total_votes_for_poll(poll_id)

    # Add player names and medals
    conn = get_connection()
    try:
        for i, r in enumerate(results):
            player_row = conn.execute(
                'SELECT name, photo_url FROM players WHERE player_id = ? AND match_id = ?',
                (r['player_id'], poll.get('match_id', ''))
            ).fetchone()
            r['player_name'] = player_row['name'] if player_row else r['player_id']
            r['photo_url'] = player_row['photo_url'] if player_row else ''
            if i == 0:
                r['medal'] = 'gold'
            elif i == 1:
                r['medal'] = 'silver'
            elif i == 2:
                r['medal'] = 'bronze'
            else:
                r['medal'] = None
    finally:
        conn.close()

    # Get best/worst match stats across all polls
    all_stats = get_all_polls_stats()

    # Compute most controversial player (highest std_dev)
    controversial_players = _compute_controversial(poll_id)
    controversial_player = controversial_players[0] if controversial_players else None

    return jsonify({
        "success": True,
        "poll": poll,
        "results": results,
        "total_voters": total_voters,
        "best_match": all_stats.get('best_match'),
        "worst_match": all_stats.get('worst_match'),
        "controversial_player": controversial_player,
    })


@app.get("/api/match/<match_id>/events")
def api_match_events(match_id):
    """Get match events with emoji mapping."""
    events = get_match_events(match_id)
    events_list = []
    events_by_player = {}
    for ev in events:
        event_type = ev.get('event_type')
        detail = ev.get('detail', '')
        # Map event_type to emoji
        if event_type == 1:
            emoji = "\u26bd"
        elif event_type == 2:
            if 'red' in str(detail).lower():
                emoji = "\U0001f7e5"
            else:
                emoji = "\U0001f7e8"
        elif event_type == 3:
            emoji = "\u21d4\ufe0f"
        else:
            emoji = ""
        event_item = {
            'type': event_type,
            'emoji': emoji,
            'minute': ev.get('minute'),
            'detail': detail,
            'player_id': ev.get('player_id'),
        }
        events_list.append(event_item)
        pid = ev.get('player_id', '')
        if pid:
            if pid not in events_by_player:
                events_by_player[pid] = []
            events_by_player[pid].append(event_item)
    return jsonify({"success": True, "events": events_list, "events_by_player": events_by_player})


@app.get("/api/match/<match_id>/ai-ratings")
def api_match_ai_ratings(match_id):
    """Get AI (sstats) ratings for a match with player names."""
    ratings = get_ai_ratings(match_id)
    conn = get_connection()
    try:
        result = []
        for r in ratings:
            player_row = conn.execute(
                'SELECT name FROM players WHERE player_id = ? AND match_id = ?',
                (r['player_id'], match_id)
            ).fetchone()
            name = player_row['name'] if player_row else r['player_id']
            result.append({
                'player_id': r['player_id'],
                'name': name,
                'sstats_rating': r['sstats_rating'],
                'normalized_rating': r['normalized_rating'],
            })
    finally:
        conn.close()
    return jsonify({"success": True, "ratings": result})


@app.get("/api/match/<match_id>/timeline")
def api_match_timeline(match_id):
    """Get match events sorted by minute for timeline visualization."""
    events = get_match_events(match_id)
    timeline = []
    for ev in events:
        event_type = ev.get('event_type')
        detail = ev.get('detail', '')
        if event_type == 1:
            emoji = "\u26bd"
        elif event_type == 2:
            if 'red' in str(detail).lower():
                emoji = "\U0001f7e5"
            else:
                emoji = "\U0001f7e8"
        elif event_type == 3:
            emoji = "\u21d4\ufe0f"
        else:
            emoji = ""
        timeline.append({
            'minute': ev.get('minute'),
            'player_id': ev.get('player_id'),
            'event_type': event_type,
            'emoji': emoji,
            'detail': detail,
        })
    return jsonify({"success": True, "timeline": timeline})


@app.get("/api/results/<poll_id>/comparison")
def api_results_comparison(poll_id):
    """Compare user ratings vs bot ratings vs community average."""
    poll = get_poll(poll_id)
    if not poll:
        return jsonify({"success": False, "error": "poll not found"}), 404
    match_id = poll.get('match_id', '')

    # Get current user's votes
    uid = get_current_user_id()
    user_ratings = {}
    if uid:
        vote = get_user_vote(poll_id, uid)
        if vote:
            user_ratings = vote

    # Get AI ratings for the match
    ai_ratings_list = get_ai_ratings(match_id)
    bot_ratings = {r['player_id']: r['normalized_rating'] for r in ai_ratings_list}

    # Get community average
    results = get_results(poll_id)
    community_avg = {r['player_id']: r['avg_rating'] for r in results}

    return jsonify({
        "success": True,
        "user_ratings": user_ratings,
        "bot_ratings": bot_ratings,
        "community_avg": community_avg,
    })


# ═══════════════════════════════════════════════════════════════════════
#  HEATMAP & CONTROVERSIAL API
# ═══════════════════════════════════════════════════════════════════════

def _compute_heatmap(uid: int) -> dict:
    """Compute vote heatmap data for a given user."""

    conn = get_connection()
    try:
        # Get all votes by this user with player info
        user_votes = conn.execute('''
            SELECT v.player_id, v.rating, v.poll_id, pl.name, pl.position
            FROM votes v
            LEFT JOIN players pl ON pl.player_id = v.player_id
            WHERE v.user_id = ?
        ''', (uid,)).fetchall()

        if not user_votes:
            return {"players": [], "insights": []}

        # Group user votes by player_id
        player_votes = {}
        player_info = {}
        for row in user_votes:
            pid = row['player_id']
            if pid not in player_votes:
                player_votes[pid] = []
                player_info[pid] = {
                    'name': row['name'] or pid,
                    'position': row['position'] or '',
                }
            player_votes[pid].append(row['rating'])

        # Get community averages per player (across all users, all polls) - single GROUP BY query
        player_ids = list(player_votes.keys())
        community_avgs = {}
        if player_ids:
            placeholders = ','.join('?' for _ in player_ids)
            comm_rows = conn.execute(f'''
                SELECT player_id, AVG(rating) as avg_rating
                FROM votes
                WHERE player_id IN ({placeholders})
                GROUP BY player_id
            ''', player_ids).fetchall()
            for row in comm_rows:
                community_avgs[row['player_id']] = row['avg_rating'] if row['avg_rating'] is not None else 0

        # Build player results
        players = []
        position_diffs = {}  # position -> list of (user_avg - community_avg)

        for pid, ratings in player_votes.items():
            user_avg = sum(ratings) / len(ratings)
            community_avg = community_avgs.get(pid, 0)
            diff = user_avg - community_avg

            if diff > 1.5:
                bias = 'high'
            elif diff < -1.5:
                bias = 'low'
            else:
                bias = 'neutral'

            position = player_info[pid]['position']
            name = player_info[pid]['name']

            players.append({
                'player_id': pid,
                'name': name,
                'position': position,
                'user_avg': round(user_avg, 2),
                'community_avg': round(community_avg, 2),
                'bias': bias,
                'vote_count': len(ratings),
            })

            # Track position-level diffs
            if position:
                if position not in position_diffs:
                    position_diffs[position] = []
                position_diffs[position].append(diff)

        # Generate insights
        insights = []

        # Player-specific insights (> 2 points above community avg consistently)
        for p in players:
            if p['vote_count'] >= 2 and (p['user_avg'] - p['community_avg']) > 2:
                insights.append(f"You always rate {p['name']} high")

        # Position-level insights
        position_labels = {'FW': 'forward', 'MF': 'midfielder', 'DF': 'defender', 'GK': 'goalkeeper'}
        for pos, diffs in position_diffs.items():
            if not diffs:
                continue
            avg_diff = sum(diffs) / len(diffs)
            label = position_labels.get(pos, pos)
            if avg_diff < -1:
                insights.append(f"You tend to underrate {label}s")
            elif avg_diff > 1:
                insights.append(f"You tend to overrate {label}s")

        return {"players": players, "insights": insights}
    finally:
        conn.close()


@app.get("/api/heatmap/me")
def api_heatmap_me():
    """Personal vote heatmap for the current user."""
    uid = get_current_user_id()
    if not uid:
        return jsonify({"success": False, "error": "unauthorized"}), 401
    data = _compute_heatmap(uid)
    return jsonify({"success": True, **data})


@app.get("/api/heatmap/<int:uid>")
def api_heatmap_user(uid):
    """Vote heatmap for a specified user (must be self or admin)."""
    current_uid = get_current_user_id()
    if not current_uid:
        return jsonify({"success": False, "error": "unauthorized"}), 401
    if current_uid != uid and not is_admin(current_uid):
        return jsonify({"success": False, "error": "forbidden"}), 403
    data = _compute_heatmap(uid)
    return jsonify({"success": True, **data})


def _compute_controversial(poll_id):
    """Shared helper to compute controversial players sorted by std_dev (descending)."""
    poll = get_poll(poll_id)
    if not poll:
        return []

    conn = get_connection()
    try:
        rows = conn.execute('''
            SELECT player_id, rating
            FROM votes
            WHERE poll_id = ?
        ''', (poll_id,)).fetchall()

        if not rows:
            return []

        player_ratings = {}
        for row in rows:
            pid = row['player_id']
            if pid not in player_ratings:
                player_ratings[pid] = []
            player_ratings[pid].append(row['rating'])

        match_id = poll.get('match_id', '')

        players = []
        for pid, ratings in player_ratings.items():
            count = len(ratings)
            if count < 2:
                continue
            avg_rating = sum(ratings) / count
            variance = sum((r - avg_rating) ** 2 for r in ratings) / count
            std_dev = math.sqrt(variance)

            player_row = conn.execute(
                'SELECT name FROM players WHERE player_id = ? AND match_id = ?',
                (pid, match_id)
            ).fetchone()
            name = player_row['name'] if player_row else pid

            players.append({
                'player_id': pid,
                'name': name,
                'avg_rating': round(avg_rating, 2),
                'std_dev': round(std_dev, 2),
                'vote_count': count,
                'is_most_controversial': False,
            })

        players.sort(key=lambda x: x['std_dev'], reverse=True)

        if players:
            players[0]['is_most_controversial'] = True

        return players
    finally:
        conn.close()


@app.get("/api/controversial/<poll_id>")
def api_controversial(poll_id):
    """Get players sorted by rating standard deviation (most controversial first)."""
    poll = get_poll(poll_id)
    if not poll:
        return jsonify({"success": False, "error": "poll not found"}), 404

    players = _compute_controversial(poll_id)
    return jsonify({"success": True, "players": players})


# ═══════════════════════════════════════════════════════════════════════
#  ADMIN API
# ═══════════════════════════════════════════════════════════════════════

def _admin_check() -> int:
    uid = get_current_user_id()
    if not uid:
        abort(401)
    # Auto-grant admin if owner_id is 0 (first run / demo mode)
    owner = get_owner_id()
    if owner == 0:
        set_config('owner_id', str(uid))
        add_log(uid, 'auto_grant_admin', details={'reason': 'first_run'})
    if not is_admin(uid):
        abort(403)
    return uid


@app.post("/api/admin/poll/create")
def api_admin_create_poll():
    admin_id = _admin_check()
    body = request.get_json(force=True)
    poll_id = body.get("poll_id", f"poll_{int(time.time())}")
    match_id = body.get("match_id", "")
    title = body.get("title", "Голосование")
    max_r = body.get("max_rating", 15)
    game_id = body.get("game_id", "")  # sstats game ID for lineup

    # If game_id provided, get real lineup; otherwise use squad
    players = []
    if game_id:
        players = get_chelsea_players_from_game(game_id)
    if not players:
        players = get_chelsea_squad()
    if not players:
        return jsonify({"success": False, "error": "could not fetch players"}), 500

    # Set max_rating based on actual player count when game_id is provided
    if game_id and players:
        max_r = len(players) - 1

    poll = create_poll(poll_id, match_id, title, max_r)

    conn = get_connection()
    try:
        conn.execute('DELETE FROM players WHERE match_id = ?', (match_id,))
        for p in players:
            conn.execute('''
                INSERT INTO players (player_id, match_id, name, number, position, photo_url, is_starter)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (p['id'], match_id, p['name'], p.get('number', ''),
                  p.get('position', ''), p.get('photo_url', ''), int(p.get('is_starter', False))))
        conn.commit()
    finally:
        conn.close()

    set_config("current_poll_id", poll_id)
    set_config("current_match_id", match_id)
    add_log(admin_id, "create_poll", details={"poll_id": poll_id, "players": len(players)})
    return jsonify({"success": True, "poll": poll, "players_count": len(players)})


@app.post("/api/admin/poll/close/<poll_id>")
def api_admin_close_poll(poll_id):
    admin_id = _admin_check()
    close_poll(poll_id)
    # Resolve predictions for this poll
    results = get_results(poll_id)
    if results:
        best_player_id = results[0]['player_id']
        resolve_predictions(poll_id, best_player_id)
        # Check prediction challenges for top-3 predictions
        top3_ids = [r['player_id'] for r in results[:3]]
        predictions = get_predictions_for_poll(poll_id)
        for pred in predictions:
            if pred['player_id'] in top3_ids:
                check_challenge_progress(pred['user_id'], 'prediction_top3', {})
    add_log(admin_id, "close_poll", details={"poll_id": poll_id})
    auto_post_results_to_channel(poll_id)
    threading.Thread(target=generate_post_match_report, args=(poll_id,), daemon=True).start()
    return jsonify({"success": True})


@app.post("/api/admin/config")
def api_admin_config():
    admin_id = _admin_check()
    body = request.get_json(force=True)
    allowed = {"voting_period_hours", "max_rating", "sstats_token", "default_background_url", "bot_name",
               "auto_create_polls", "auto_close_polls", "auto_notify", "notify_chat_id", "allow_revote_hours"}
    # Validate voting_period_hours is a positive integer
    if "voting_period_hours" in body:
        try:
            vph = int(body["voting_period_hours"])
            if vph <= 0:
                return jsonify({"success": False, "error": "voting_period_hours must be a positive integer"}), 400
        except (ValueError, TypeError):
            return jsonify({"success": False, "error": "voting_period_hours must be a positive integer"}), 400
    for k, v in body.items():
        if k in allowed:
            set_config(k, str(v))
    add_log(admin_id, "update_config", details=body)
    return jsonify({"success": True})


@app.post("/api/admin/channel-config")
def api_admin_channel_config():
    """Configure channel auto-post settings."""
    admin_id = _admin_check()
    body = request.get_json(force=True)
    results_chat_id = body.get('results_chat_id')
    results_template = body.get('results_template')
    announce_matches = body.get('announce_matches')

    if results_template is not None and results_template not in ('top3', 'top5', 'full'):
        return jsonify({"success": False, "error": "results_template must be one of: top3, top5, full"}), 400

    if results_chat_id is not None:
        # Validate that results_chat_id looks like a numeric Telegram chat ID
        chat_id_str = str(results_chat_id).strip()
        if chat_id_str and not chat_id_str.lstrip('-').isdigit():
            return jsonify({"success": False, "error": "results_chat_id must be a numeric Telegram chat ID"}), 400
        set_config('results_chat_id', chat_id_str)
    if results_template is not None:
        set_config('results_template', str(results_template))
    if announce_matches is not None:
        set_config('announce_matches', str(announce_matches))

    add_log(admin_id, "update_channel_config", details=body)
    return jsonify({"success": True})


@app.get("/api/admin/scheduler/status")
def api_admin_scheduler_status():
    _admin_check()
    cfg = get_config()
    job = scheduler.get_job('scheduled_tasks')
    next_run = str(job.next_run_time) if job and job.next_run_time else None
    return jsonify({
        "success": True,
        "scheduler": {
            "running": scheduler.running,
            "next_run_time": next_run,
            "auto_create_polls": cfg.get("auto_create_polls", "1"),
            "auto_close_polls": cfg.get("auto_close_polls", "1"),
            "auto_notify": cfg.get("auto_notify", "1"),
            "notify_chat_id": cfg.get("notify_chat_id", ""),
            "voting_period_hours": cfg.get("voting_period_hours", "24"),
        }
    })


@app.get("/api/admin/monitoring")
def api_admin_monitoring():
    _admin_check()
    cfg = get_config()
    job = scheduler.get_job('scheduled_tasks')
    next_run = str(job.next_run_time) if job and job.next_run_time else None
    last_run = cfg.get('last_scheduler_run', '')
    api_errors = int(cfg.get('api_error_count', '0'))
    conn = get_connection()
    try:
        total_users = conn.execute("SELECT COUNT(*) as c FROM profiles").fetchone()['c']
        total_votes = conn.execute("SELECT COUNT(*) as c FROM votes").fetchone()['c']
        total_polls = conn.execute("SELECT COUNT(*) as c FROM polls").fetchone()['c']
    finally:
        conn.close()
    return jsonify({
        "success": True,
        "last_scheduler_run": last_run,
        "api_error_count": api_errors,
        "scheduler_running": scheduler.running,
        "scheduler_next_run": next_run,
        "total_users": total_users,
        "total_votes": total_votes,
        "total_polls": total_polls,
        "uptime": time.time(),
    })


@app.post("/api/admin/monitoring/reset")
def api_admin_monitoring_reset():
    admin_id = _admin_check()
    set_config('api_error_count', '0')
    add_log(admin_id, "reset_api_error_count")
    return jsonify({"success": True})


# ── Challenge API endpoints ────────────────────────────────────────────

@app.get("/api/challenges")
def api_challenges():
    uid = get_current_user_id()
    challenges = get_active_challenges()
    user_progress = {}
    if uid:
        progress_list = get_user_challenge_progress(uid)
        for p in progress_list:
            user_progress[p['challenge_id']] = {
                'progress': p['progress'],
                'completed': p['completed'],
                'completed_at': p['completed_at']
            }
    result = []
    for ch in challenges:
        ch_data = dict(ch)
        prog = user_progress.get(ch['id'], {'progress': 0, 'completed': 0, 'completed_at': None})
        ch_data['user_progress'] = prog['progress']
        ch_data['user_completed'] = prog['completed']
        ch_data['user_completed_at'] = prog['completed_at']
        result.append(ch_data)
    return jsonify({"success": True, "challenges": result})


@app.post("/api/admin/challenges/create")
def api_admin_create_challenge():
    admin_id = _admin_check()
    body = request.get_json(force=True)
    title = body.get('title', '')
    description = body.get('description', '')
    challenge_type = body.get('type', 'custom')
    target = int(body.get('target', 1))
    reward_xp = int(body.get('reward_xp', 20))
    end_time = body.get('end_time')

    if not title:
        return jsonify({"success": False, "error": "title required"}), 400
    if target < 1:
        return jsonify({"success": False, "error": "target must be >= 1"}), 400

    now = time.time()
    ch_id = create_challenge(
        title=title,
        description=description,
        challenge_type=challenge_type,
        target=target,
        reward_xp=reward_xp,
        start_time=now,
        end_time=float(end_time) if end_time else now + 7 * 86400,
        created_by=admin_id
    )
    add_log(admin_id, "create_challenge", details={"challenge_id": ch_id, "title": title})
    return jsonify({"success": True, "challenge_id": ch_id})


@app.post("/api/admin/challenges/toggle")
def api_admin_toggle_challenge():
    admin_id = _admin_check()
    body = request.get_json(force=True)
    challenge_id = int(body.get('challenge_id', 0))
    active = bool(body.get('active', True))

    ch = get_challenge_by_id(challenge_id)
    if not ch:
        return jsonify({"success": False, "error": "challenge not found"}), 404

    toggle_challenge(challenge_id, active)
    add_log(admin_id, "toggle_challenge", details={"challenge_id": challenge_id, "active": active})
    return jsonify({"success": True})


@app.get("/api/admin/admins")
def api_admin_list_admins():
    _admin_check()
    return jsonify({"success": True, "admins": list_admins()})


# ── Awards API endpoints ───────────────────────────────────────────────

@app.get("/api/awards")
def api_awards():
    """Get all recent awards."""
    awards = get_all_awards(limit=50)
    return jsonify({"success": True, "awards": awards})


@app.get("/api/awards/user/<int:uid>")
def api_awards_user(uid):
    """Get awards for a specific user."""
    awards = get_user_awards(uid)
    return jsonify({"success": True, "awards": awards})


@app.post("/api/admin/admins/add")
def api_admin_add_admin():
    requester = _admin_check()
    body = request.get_json(force=True)
    target_id = int(body.get("user_id", 0))
    if target_id <= 0:
        return jsonify({"success": False, "error": "invalid user_id"}), 400
    add_admin(target_id, body.get("username", ""), requester)
    add_log(requester, "add_admin", target_user_id=target_id)
    return jsonify({"success": True})


@app.post("/api/admin/admins/remove")
def api_admin_remove_admin():
    requester = _admin_check()
    body = request.get_json(force=True)
    target_id = int(body.get("user_id", 0))
    remove_admin(target_id)
    add_log(requester, "remove_admin", target_user_id=target_id)
    return jsonify({"success": True})


@app.get("/api/admin/logs")
def api_admin_logs():
    _admin_check()
    limit = request.args.get("limit", 50, type=int)
    return jsonify({"success": True, "logs": get_logs(limit)})


@app.get("/api/admin/votes/<poll_id>")
def api_admin_get_votes(poll_id):
    """Get all votes for a poll with user details — for admin review."""
    _admin_check()
    conn = get_connection()
    try:
        rows = conn.execute('''
            SELECT v.user_id, v.player_id, v.rating, v.batch_id, v.timestamp,
                   p.username, p.first_name, p.custom_id, p.auto_id,
                   pl.name as player_name, pl.photo_url
            FROM votes v
            LEFT JOIN profiles p ON p.user_id = v.user_id
            LEFT JOIN players pl ON pl.player_id = v.player_id AND pl.match_id = ?
            WHERE v.poll_id = ?
            ORDER BY v.timestamp DESC, v.user_id
        ''', (poll_id, poll_id)).fetchall()
        votes = [dict(r) for r in rows]

        # Group by user: {user_id: {profile, votes: {player_id: rating}}}
        by_user = {}
        for v in rows:
            uid = v['user_id']
            if uid not in by_user:
                by_user[uid] = {
                    'user_id': uid,
                    'username': v['username'] or v['first_name'] or f"User {uid}",
                    'custom_id': v['custom_id'],
                    'auto_id': v['auto_id'],
                    'votes': {},
                    'timestamp': v['timestamp'],
                }
            by_user[uid]['votes'][v['player_id']] = v['rating']

        return jsonify({
            "success": True,
            "votes": votes,
            "by_user": list(by_user.values()),
            "total_voters": len(by_user),
        })
    finally:
        conn.close()


@app.post("/api/admin/vote/adjust")
def api_admin_adjust_vote():
    """Adjust a user's vote and log it."""
    admin_id = _admin_check()
    body = request.get_json(force=True)
    poll_id = body.get("poll_id", "")
    target_uid = int(body.get("user_id", 0))
    player_id = body.get("player_id", "")
    new_rating = int(body.get("new_rating", -1))
    if not poll_id or target_uid <= 0 or not player_id or new_rating < 0:
        return jsonify({"success": False, "error": "missing fields"}), 400
    adjust_vote(poll_id, target_uid, player_id, new_rating, admin_id)
    return jsonify({"success": True})


@app.post("/api/admin/vote/remove")
def api_admin_remove_user_votes(poll_id_override=None):
    """Remove all votes from a user in a poll."""
    admin_id = _admin_check()
    body = request.get_json(force=True)
    poll_id = body.get("poll_id", "")
    target_uid = int(body.get("user_id", 0))
    if not poll_id or target_uid <= 0:
        return jsonify({"success": False, "error": "missing fields"}), 400
    conn = get_connection()
    try:
        conn.execute('DELETE FROM votes WHERE poll_id = ? AND user_id = ?', (poll_id, target_uid))
        conn.commit()
    finally:
        conn.close()
    add_log(admin_id, "remove_votes", target_user_id=target_uid,
            details={"poll_id": poll_id})
    return jsonify({"success": True})


# ── run ────────────────────────────────────────────────────────────────

def start_ngrok(port: int) -> str | None:
    try:
        from pyngrok import ngrok
        token = os.getenv("NGROK_AUTH_TOKEN")
        if token:
            ngrok.set_auth_token(token)
        tunnel = ngrok.connect(port, "http")
        url = tunnel.public_url
        print(f"  🌍 ngrok: {url}")
        return url
    except Exception as e:
        print(f"  ⚠️  ngrok: {e}")
        return None


# ── Background Scheduler ───────────────────────────────────────────────

def check_reminder_notifications():
    """Send reminder notifications to users who haven't voted when poll is about to close."""
    cfg = get_config()
    if cfg.get('auto_notify') != '1':
        return
    voting_hours = int(cfg.get('voting_period_hours', 24))
    now = time.time()
    open_polls = list_polls(status='open')

    for poll in open_polls:
        created_at = poll.get('created_at', 0)
        if not created_at:
            continue
        deadline = created_at + voting_hours * 3600
        time_until_close = deadline - now

        # Send reminder if deadline is within 1.5 to 2.5 hours
        if 1.5 * 3600 <= time_until_close <= 2.5 * 3600:
            poll_id = poll['poll_id']
            # Get users with remind_before_close=1 who haven't voted and haven't been reminded
            conn = get_connection()
            try:
                rows = conn.execute('''
                    SELECT np.user_id
                    FROM notification_prefs np
                    WHERE np.remind_before_close = 1
                    AND np.user_id NOT IN (
                        SELECT DISTINCT user_id FROM votes WHERE poll_id = ?
                    )
                    AND np.user_id NOT IN (
                        SELECT user_id FROM reminders_sent WHERE poll_id = ?
                    )
                ''', (poll_id, poll_id)).fetchall()
                for row in rows:
                    user_id = row['user_id']
                    title = poll.get('title', 'Poll')
                    text = f"Reminder: voting for <b>{title}</b> closes in ~2 hours! Don't forget to vote."
                    send_telegram_message(user_id, text)
                    # Record that we sent this reminder
                    conn.execute(
                        'INSERT OR IGNORE INTO reminders_sent (poll_id, user_id) VALUES (?, ?)',
                        (poll_id, user_id)
                    )
                conn.commit()
            finally:
                conn.close()


def check_scheduler_health():
    """Check if scheduler ran recently. Alert admin if more than 1 hour since last run."""
    try:
        cfg = get_config()
        last_run = cfg.get('last_scheduler_run', '')
        if not last_run:
            return
        elapsed = time.time() - float(last_run)
        if elapsed > 3600:
            chat_id = cfg.get('notify_chat_id', '')
            if chat_id:
                send_telegram_message(
                    chat_id,
                    "\u26a0\ufe0f <b>Scheduler Alert</b>\n"
                    f"Last scheduler run was {int(elapsed // 60)} minutes ago.\n"
                    "The scheduler may not be running properly."
                )
    except Exception:
        pass


def check_expired_challenges():
    """Mark expired challenges as inactive and create new default challenges."""
    now = time.time()
    challenges = get_active_challenges()
    expired_any = False
    for ch in challenges:
        if ch.get('end_time') and ch['end_time'] < now:
            toggle_challenge(ch['id'], False)
            expired_any = True
    if expired_any:
        create_default_challenges()


# ── Monthly Awards ─────────────────────────────────────────────────────

def compute_monthly_awards(year, month):
    """Compute the 4 award categories for a given month. Returns list of award dicts."""
    month_str = f"{year:04d}-{month:02d}"
    conn = get_connection()
    try:
        # Get polls closed in that month
        month_start = f"{year:04d}-{month:02d}"
        # Find polls created in that month by timestamp range
        import calendar
        days_in_month = calendar.monthrange(year, month)[1]
        from datetime import datetime
        ts_start = datetime(year, month, 1).timestamp()
        ts_end = datetime(year, month, days_in_month, 23, 59, 59).timestamp()

        # Get all closed polls in that month
        polls_in_month = conn.execute(
            "SELECT poll_id FROM polls WHERE status = 'closed' AND created_at >= ? AND created_at <= ?",
            (ts_start, ts_end)
        ).fetchall()
        poll_ids = [p['poll_id'] for p in polls_in_month]

        if not poll_ids:
            return []

        placeholders = ','.join('?' * len(poll_ids))
        awards = []

        # 1. Most Accurate - user whose avg rating is closest to community average
        # Community average per player per poll, then user's deviation from that
        user_deviations = conn.execute(f'''
            SELECT v.user_id,
                   AVG(ABS(v.rating - poll_avg.avg_rating)) as avg_deviation
            FROM votes v
            JOIN (
                SELECT poll_id, player_id, AVG(rating) as avg_rating
                FROM votes
                WHERE poll_id IN ({placeholders})
                GROUP BY poll_id, player_id
            ) poll_avg ON poll_avg.poll_id = v.poll_id AND poll_avg.player_id = v.player_id
            WHERE v.poll_id IN ({placeholders})
            GROUP BY v.user_id
            HAVING COUNT(DISTINCT v.poll_id) >= 1
            ORDER BY avg_deviation ASC
            LIMIT 1
        ''', poll_ids + poll_ids).fetchone()

        if user_deviations:
            awards.append({
                'user_id': user_deviations['user_id'],
                'award_type': 'most_accurate',
                'month': month_str,
                'details': {'avg_deviation': round(user_deviations['avg_deviation'], 2)}
            })

        # 2. Most Active - user who participated in the most polls that month
        most_active = conn.execute(f'''
            SELECT user_id, COUNT(DISTINCT poll_id) as polls_participated
            FROM votes
            WHERE poll_id IN ({placeholders})
            GROUP BY user_id
            ORDER BY polls_participated DESC
            LIMIT 1
        ''', poll_ids).fetchone()

        if most_active:
            awards.append({
                'user_id': most_active['user_id'],
                'award_type': 'most_active',
                'month': month_str,
                'details': {'polls_participated': most_active['polls_participated']}
            })

        # 3. Best Predictor - user with highest prediction points that month
        best_predictor = conn.execute(f'''
            SELECT user_id, SUM(points_earned) as total_points
            FROM prediction_results
            WHERE poll_id IN ({placeholders})
            GROUP BY user_id
            ORDER BY total_points DESC
            LIMIT 1
        ''', poll_ids).fetchone()

        if best_predictor and best_predictor['total_points'] > 0:
            awards.append({
                'user_id': best_predictor['user_id'],
                'award_type': 'best_predictor',
                'month': month_str,
                'details': {'total_points': best_predictor['total_points']}
            })

        # 4. Streak Record - user with longest streak earned DURING that month
        # Calculate consecutive poll participation within the month
        # Get all users who voted in this month's polls, ordered by poll creation time
        user_poll_participation = conn.execute(f'''
            SELECT DISTINCT v.user_id, p.poll_id, p.created_at
            FROM votes v
            JOIN polls p ON p.poll_id = v.poll_id
            WHERE v.poll_id IN ({placeholders})
            ORDER BY v.user_id, p.created_at ASC
        ''', poll_ids).fetchall()

        # Compute streaks per user within the month
        best_streak_user = None
        best_streak_val = 0
        if user_poll_participation:
            # Group by user_id
            from itertools import groupby
            sorted_rows = sorted(user_poll_participation, key=lambda r: r['user_id'])
            for uid, rows in groupby(sorted_rows, key=lambda r: r['user_id']):
                user_polls = sorted(set(r['poll_id'] for r in rows))
                # The streak is simply how many consecutive polls (in order) the user participated in
                # Since all these polls are in the same month, the streak = number of distinct polls voted in
                streak_count = len(user_polls)
                if streak_count > best_streak_val:
                    best_streak_val = streak_count
                    best_streak_user = uid

        if best_streak_user and best_streak_val > 0:
            awards.append({
                'user_id': best_streak_user,
                'award_type': 'streak_record',
                'month': month_str,
                'details': {'max_streak': best_streak_val}
            })

        return awards
    finally:
        conn.close()


def award_monthly_winners(year, month):
    """Compute awards, save to DB, grant XP, post to channel."""
    awards = compute_monthly_awards(year, month)
    if not awards:
        return

    month_str = f"{year:04d}-{month:02d}"
    cfg = get_config()

    award_type_labels = {
        'most_accurate': '\U0001F3AF Most Accurate',
        'most_active': '\U0001F525 Most Active',
        'best_predictor': '\U0001F52E Best Predictor',
        'streak_record': '\U0001F4AA Streak Record',
    }

    message_lines = [f"\U0001F3C6 <b>Monthly Awards - {month_str}</b>\n"]

    for award in awards:
        save_award(award['user_id'], award['award_type'], award['month'], award['details'])
        add_xp(award['user_id'], 100, f"award_{award['award_type']}_{month_str}")

        # Get user name for message
        profile = get_profile(award['user_id'])
        name = 'Unknown'
        if profile:
            name = profile.get('first_name') or profile.get('username') or str(award['user_id'])

        label = award_type_labels.get(award['award_type'], award['award_type'])
        details = award.get('details', {})
        detail_str = ''
        if award['award_type'] == 'most_accurate':
            detail_str = f" (avg deviation: {details.get('avg_deviation', '?')})"
        elif award['award_type'] == 'most_active':
            detail_str = f" ({details.get('polls_participated', '?')} polls)"
        elif award['award_type'] == 'best_predictor':
            detail_str = f" ({details.get('total_points', '?')} points)"
        elif award['award_type'] == 'streak_record':
            detail_str = f" ({details.get('max_streak', '?')} polls streak)"

        message_lines.append(f"\U0001F947 {label}: <b>{html.escape(name)}</b>{detail_str}")

    message_lines.append("\n\U0001F389 Congratulations to all winners! +100 XP each!")

    # Post to channel
    chat_id = cfg.get('notify_chat_id', '') or cfg.get('results_chat_id', '')
    if chat_id:
        send_telegram_message(chat_id, '\n'.join(message_lines))


def check_monthly_awards():
    """Check if today is the 1st and awards for last month haven't been computed."""
    cfg = get_config()
    if cfg.get('awards_enabled') != '1':
        return

    from datetime import datetime, timedelta
    now = datetime.now()
    if now.day != 1:
        return

    # Compute for previous month
    first_of_this_month = datetime(now.year, now.month, 1)
    last_month_date = first_of_this_month - timedelta(days=1)
    year = last_month_date.year
    month = last_month_date.month
    month_str = f"{year:04d}-{month:02d}"

    # Check if already computed
    existing = get_month_awards(month_str)
    if existing:
        return

    award_monthly_winners(year, month)


def scheduled_tasks():
    """Run all scheduled background tasks."""
    check_scheduler_health()
    check_auto_close_polls()
    check_and_auto_create_poll()
    check_reminder_notifications()
    check_expired_challenges()
    check_monthly_awards()
    set_config('last_scheduler_run', str(time.time()))


scheduler = BackgroundScheduler(daemon=True)
scheduler.add_job(scheduled_tasks, 'interval', minutes=30, id='scheduled_tasks')

# Start scheduler at module level for WSGI/Railway deployment
try:
    scheduler.start()
except Exception:
    pass

atexit.register(lambda: scheduler.shutdown(wait=False) if scheduler.running else None)


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))

    railway_env = os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("RAILWAY_STATIC_URL")
    if railway_env:
        print(f"\n  🚂 Railway (port {port})")
    else:
        url = start_ngrok(port)
        if url:
            os.environ["MINI_APP_URL"] = url
            set_config("mini_app_url", url)

    # Ensure scheduler is running
    try:
        if not scheduler.running:
            scheduler.start()
    except Exception:
        pass

    print(f"  🚀 http://localhost:{port}")
    print(f"  📍 /api/health\n")

    app.run(host="0.0.0.0", port=port, debug=False)
