import sqlite3
import time
import json
from typing import Optional, List, Dict, Any

import os

# Use /tmp for SQLite on Railway (ephemeral), or /app/data if volume mounted
DB_DIR = os.getenv('DB_DIR', '/tmp')
DB_PATH = os.path.join(DB_DIR, 'chelsea_bot.db')


def get_connection():
    conn = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create all tables if they don't exist."""
    conn = get_connection()
    try:
        cur = conn.cursor()

        # ── config ──────────────────────────────────────────────
        cur.execute('''
            CREATE TABLE IF NOT EXISTS config (
                key   TEXT PRIMARY KEY,
                value TEXT
            )
        ''')

        # ── admin list (in addition to owner_id in config) ───────
        cur.execute('''
            CREATE TABLE IF NOT EXISTS admins (
                user_id     INTEGER PRIMARY KEY,
                username    TEXT,
                added_by    INTEGER,
                added_at    REAL NOT NULL
            )
        ''')

        # ── profiles / custom IDs ───────────────────────────────
        cur.execute('''
            CREATE TABLE IF NOT EXISTS profiles (
                user_id         INTEGER PRIMARY KEY,
                username        TEXT,
                first_name      TEXT,
                last_name       TEXT,
                custom_id       TEXT UNIQUE,
                auto_id         TEXT NOT NULL,
                total_votes     INTEGER DEFAULT 0,
                language        TEXT DEFAULT 'ru',
                theme           TEXT DEFAULT 'dark',
                notifications   INTEGER DEFAULT 1,
                background_url  TEXT,
                created_at      REAL NOT NULL
            )
        ''')

        # ── vote polls (a poll = one match voting round) ────────
        cur.execute('''
            CREATE TABLE IF NOT EXISTS polls (
                poll_id     TEXT PRIMARY KEY,
                match_id    TEXT NOT NULL,
                title       TEXT,
                status      TEXT DEFAULT 'open',   -- open / closed
                max_rating  INTEGER DEFAULT 10,
                created_at  REAL NOT NULL,
                closed_at   REAL
            )
        ''')

        # ── individual votes (batch / poll based) ───────────────
        cur.execute('''
            CREATE TABLE IF NOT EXISTS votes (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                poll_id     TEXT NOT NULL,
                user_id     INTEGER NOT NULL,
                player_id   TEXT NOT NULL,
                rating      INTEGER NOT NULL,
                batch_id    TEXT,
                timestamp   REAL NOT NULL,
                FOREIGN KEY(poll_id) REFERENCES polls(poll_id)
            )
        ''')

        # ── admin action log ────────────────────────────────────
        cur.execute('''
            CREATE TABLE IF NOT EXISTS admin_logs (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_user_id   INTEGER NOT NULL,
                target_user_id  INTEGER,
                action          TEXT NOT NULL,
                details         TEXT,
                timestamp       REAL NOT NULL
            )
        ''')

        # ── global background (set by admin) ────────────────────
        cur.execute('''
            CREATE TABLE IF NOT EXISTS backgrounds (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                label       TEXT NOT NULL,
                url         TEXT NOT NULL,
                is_default  INTEGER DEFAULT 0,
                uploaded_by INTEGER,
                uploaded_at REAL NOT NULL
            )
        ''')

        # ── players cache ───────────────────────────────────────
        cur.execute('''
            CREATE TABLE IF NOT EXISTS players (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                player_id   TEXT NOT NULL,
                match_id    TEXT,
                name        TEXT NOT NULL,
                number      INTEGER DEFAULT 0,
                position    TEXT DEFAULT '',
                photo_url   TEXT DEFAULT '',
                is_starter  INTEGER DEFAULT 0,
                UNIQUE(player_id, match_id)
            )
        ''')

        # ── predictions ─────────────────────────────────────────
        cur.execute('''
            CREATE TABLE IF NOT EXISTS predictions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                poll_id     TEXT NOT NULL,
                user_id     INTEGER NOT NULL,
                player_id   TEXT NOT NULL,
                timestamp   REAL NOT NULL,
                UNIQUE(poll_id, user_id)
            )
        ''')

        # ── prediction results ──────────────────────────────────
        cur.execute('''
            CREATE TABLE IF NOT EXISTS prediction_results (
                id                      INTEGER PRIMARY KEY AUTOINCREMENT,
                poll_id                 TEXT NOT NULL,
                user_id                 INTEGER NOT NULL,
                predicted_player_id     TEXT NOT NULL,
                actual_best_player_id   TEXT NOT NULL,
                points_earned           INTEGER DEFAULT 0,
                timestamp               REAL NOT NULL
            )
        ''')

        # ── mini games ──────────────────────────────────────────
        cur.execute('''
            CREATE TABLE IF NOT EXISTS mini_games (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                match_id    TEXT NOT NULL,
                user_id     INTEGER NOT NULL,
                game_type   TEXT NOT NULL,
                guess       TEXT NOT NULL,
                result      TEXT,
                points      INTEGER DEFAULT 0,
                timestamp   REAL NOT NULL,
                UNIQUE(match_id, user_id, game_type)
            )
        ''')

        # ── referrals ──────────────────────────────────────────
        cur.execute('''
            CREATE TABLE IF NOT EXISTS referrals (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_user_id    INTEGER NOT NULL,
                referred_user_id    INTEGER NOT NULL,
                timestamp           REAL NOT NULL,
                UNIQUE(referred_user_id)
            )
        ''')

        # ── notification preferences ───────────────────────────
        cur.execute('''
            CREATE TABLE IF NOT EXISTS notification_prefs (
                user_id             INTEGER PRIMARY KEY,
                remind_before_close INTEGER DEFAULT 1,
                new_poll_notify     INTEGER DEFAULT 1,
                results_notify      INTEGER DEFAULT 1
            )
        ''')

        # ── reminders sent (deduplication for reminder notifications) ──
        cur.execute('''
            CREATE TABLE IF NOT EXISTS reminders_sent (
                poll_id     TEXT NOT NULL,
                user_id     INTEGER NOT NULL,
                UNIQUE(poll_id, user_id)
            )
        ''')

        # ── XP log ───────────────────────────────────────────────
        cur.execute('''
            CREATE TABLE IF NOT EXISTS xp_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL,
                amount      INTEGER NOT NULL,
                reason      TEXT,
                timestamp   REAL NOT NULL
            )
        ''')

        # ── user XP totals ──────────────────────────────────────
        cur.execute('''
            CREATE TABLE IF NOT EXISTS user_xp (
                user_id     INTEGER PRIMARY KEY,
                total_xp    INTEGER DEFAULT 0,
                level       TEXT DEFAULT 'Новичок'
            )
        ''')

        # ── streaks ─────────────────────────────────────────────
        cur.execute('''
            CREATE TABLE IF NOT EXISTS streaks (
                user_id             INTEGER PRIMARY KEY,
                current_streak      INTEGER DEFAULT 0,
                max_streak          INTEGER DEFAULT 0,
                last_vote_poll_id   TEXT
            )
        ''')

        # ── match events (goals, cards, substitutions) ──────────
        cur.execute('''
            CREATE TABLE IF NOT EXISTS match_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                match_id TEXT NOT NULL,
                player_id TEXT,
                event_type INTEGER NOT NULL,
                minute INTEGER,
                detail TEXT,
                UNIQUE(match_id, player_id, event_type, minute)
            )
        ''')

        # ── AI ratings (sstats player ratings per match) ────────
        cur.execute('''
            CREATE TABLE IF NOT EXISTS ai_ratings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                match_id TEXT NOT NULL,
                player_id TEXT NOT NULL,
                sstats_rating REAL,
                normalized_rating REAL,
                UNIQUE(match_id, player_id)
            )
        ''')

        # ── challenges ──────────────────────────────────────────
        cur.execute('''
            CREATE TABLE IF NOT EXISTS challenges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT,
                type TEXT NOT NULL,
                target INTEGER NOT NULL,
                reward_xp INTEGER DEFAULT 20,
                start_time REAL,
                end_time REAL,
                active INTEGER DEFAULT 1,
                created_by INTEGER
            )
        ''')

        # ── challenge_progress ──────────────────────────────────
        cur.execute('''
            CREATE TABLE IF NOT EXISTS challenge_progress (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                challenge_id INTEGER NOT NULL,
                progress INTEGER DEFAULT 0,
                completed INTEGER DEFAULT 0,
                completed_at REAL,
                UNIQUE(user_id, challenge_id)
            )
        ''')

        # ── awards ──────────────────────────────────────────────
        cur.execute('''
            CREATE TABLE IF NOT EXISTS awards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                award_type TEXT NOT NULL,
                month TEXT NOT NULL,
                year INTEGER,
                details TEXT,
                awarded_at REAL NOT NULL,
                UNIQUE(user_id, award_type, month)
            )
        ''')

        # ── fpl_points ──────────────────────────────────────────
        cur.execute('''
            CREATE TABLE IF NOT EXISTS fpl_points (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                player_name TEXT NOT NULL,
                player_id TEXT,
                match_id TEXT,
                fpl_points INTEGER,
                gameweek INTEGER,
                fpl_player_id INTEGER,
                cached_at REAL NOT NULL
            )
        ''')
        cur.execute('''
            CREATE INDEX IF NOT EXISTS idx_fpl_points_name_gw
            ON fpl_points (player_name, gameweek)
        ''')

        # ── fpl_cache ───────────────────────────────────────────
        cur.execute('''
            CREATE TABLE IF NOT EXISTS fpl_cache (
                key TEXT PRIMARY KEY,
                data TEXT NOT NULL,
                cached_at REAL NOT NULL
            )
        ''')

        # ── match_analytics (pre-match analytics) ──────────────
        cur.execute('''
            CREATE TABLE IF NOT EXISTS match_analytics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                match_id TEXT UNIQUE NOT NULL,
                poll_id TEXT,
                opponent_name TEXT,
                opponent_id INTEGER,
                opponent_form TEXT,
                h2h_stats TEXT,
                predicted_result TEXT,
                analytics_data TEXT,
                generated_at REAL NOT NULL
            )
        ''')

        # ── match_reports (post-match reports) ─────────────────
        cur.execute('''
            CREATE TABLE IF NOT EXISTS match_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                poll_id TEXT UNIQUE NOT NULL,
                match_id TEXT,
                report_text TEXT NOT NULL,
                report_data TEXT,
                generated_at REAL NOT NULL
            )
        ''')

        # ── avatar column on profiles ──────────────────────────
        try:
            cur.execute("ALTER TABLE profiles ADD COLUMN avatar TEXT DEFAULT '0'")
        except Exception:
            pass  # column already exists

        # ── default config values ───────────────────────────────
        import os as _os
        defaults = {
            'voting_period_hours': '24',
            'max_rating': '10',
            'current_match_id': '',
            'current_poll_id': '',
            'sstats_token': '',
            'owner_id': _os.getenv('OWNER_ID', '0'),
            'default_background_url': '',
            'bot_name': 'Chelsea Voting Bot',
            'bot_description': 'Оценивайте игроков Челси после матчей',
            'auto_create_polls': '1',
            'auto_close_polls': '1',
            'auto_notify': '1',
            'notify_chat_id': '',
            'allow_revote_hours': '0',
            'results_chat_id': '',
            'results_template': 'top5',
            'announce_matches': '1',
            'last_scheduler_run': '',
            'api_error_count': '0',
            'awards_enabled': '1',
            'monitoring_admin_chat_id': '',
        }
        for k, v in defaults.items():
            cur.execute('INSERT OR IGNORE INTO config (key, value) VALUES (?, ?)', (k, v))

        conn.commit()
    finally:
        conn.close()


# ──────────────────────────────────────────────────────────────────────
# Config helpers
# ──────────────────────────────────────────────────────────────────────

def get_config() -> Dict[str, str]:
    conn = get_connection()
    try:
        rows = conn.execute('SELECT key, value FROM config').fetchall()
        return {r['key']: r['value'] for r in rows}
    finally:
        conn.close()


def set_config(key: str, value: str):
    conn = get_connection()
    try:
        conn.execute('UPDATE config SET value = ? WHERE key = ?', (value, key))
        conn.commit()
    finally:
        conn.close()


def get_owner_id() -> int:
    cfg = get_config()
    return int(cfg.get('owner_id', '0'))


# ──────────────────────────────────────────────────────────────────────
# Admin helpers
# ──────────────────────────────────────────────────────────────────────

def is_admin(user_id: int) -> bool:
    if user_id == get_owner_id():
        return True
    conn = get_connection()
    try:
        row = conn.execute('SELECT 1 FROM admins WHERE user_id = ?', (user_id,)).fetchone()
        return row is not None
    finally:
        conn.close()


def add_admin(user_id: int, username: str, added_by: int):
    conn = get_connection()
    try:
        conn.execute(
            'INSERT OR REPLACE INTO admins (user_id, username, added_by, added_at) VALUES (?, ?, ?, ?)',
            (user_id, username, added_by, time.time())
        )
        conn.commit()
    finally:
        conn.close()


def remove_admin(user_id: int):
    conn = get_connection()
    try:
        conn.execute('DELETE FROM admins WHERE user_id = ?', (user_id,))
        conn.commit()
    finally:
        conn.close()


def list_admins() -> List[Dict]:
    conn = get_connection()
    try:
        rows = conn.execute('SELECT * FROM admins ORDER BY added_at DESC').fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ──────────────────────────────────────────────────────────────────────
# Profile helpers
# ──────────────────────────────────────────────────────────────────────

def _generate_auto_id() -> str:
    conn = get_connection()
    try:
        count = conn.execute('SELECT COUNT(*) as c FROM profiles').fetchone()['c']
        return f'chelsea-{count + 1:03d}'
    finally:
        conn.close()


def get_or_create_profile(user_id: int, username: str = '', first_name: str = '', last_name: str = '') -> Dict:
    conn = get_connection()
    try:
        row = conn.execute('SELECT * FROM profiles WHERE user_id = ?', (user_id,)).fetchone()
        if row:
            return dict(row)
        auto_id = _generate_auto_id()
        now = time.time()
        conn.execute('''
            INSERT INTO profiles (user_id, username, first_name, last_name, auto_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (user_id, username, first_name, last_name, auto_id, now))
        conn.commit()
        row = conn.execute('SELECT * FROM profiles WHERE user_id = ?', (user_id,)).fetchone()
        return dict(row)
    finally:
        conn.close()


def update_profile(user_id: int, **kwargs):
    allowed = {'username', 'first_name', 'last_name', 'custom_id', 'language', 'theme', 'notifications', 'background_url', 'avatar'}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return
    set_clause = ', '.join(f'{k} = ?' for k in fields)
    values = list(fields.values()) + [user_id]
    conn = get_connection()
    try:
        conn.execute(f'UPDATE profiles SET {set_clause} WHERE user_id = ?', values)
        conn.commit()
    finally:
        conn.close()


def get_profile(user_id: int) -> Optional[Dict]:
    conn = get_connection()
    try:
        row = conn.execute('SELECT * FROM profiles WHERE user_id = ?', (user_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d['is_admin'] = 1 if is_admin(user_id) else 0
        return d
    finally:
        conn.close()


def get_profile_stats(user_id: int) -> Dict:
    conn = get_connection()
    try:
        total = conn.execute('SELECT COUNT(*) as c FROM votes WHERE user_id = ?', (user_id,)).fetchone()['c']
        avg = conn.execute('SELECT AVG(rating) as a FROM votes WHERE user_id = ?', (user_id,)).fetchone()['a']
        return {
            'total_votes': total,
            'avg_rating_given': round(float(avg), 2) if avg else 0.0,
        }
    finally:
        conn.close()


# ──────────────────────────────────────────────────────────────────────
# Poll helpers
# ──────────────────────────────────────────────────────────────────────

def create_poll(poll_id: str, match_id: str, title: str = '', max_rating: int = 10) -> Dict:
    conn = get_connection()
    try:
        now = time.time()
        conn.execute('''
            INSERT INTO polls (poll_id, match_id, title, max_rating, created_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (poll_id, match_id, title, max_rating, now))
        conn.commit()
        row = conn.execute('SELECT * FROM polls WHERE poll_id = ?', (poll_id,)).fetchone()
        return dict(row)
    finally:
        conn.close()


def get_poll(poll_id: str) -> Optional[Dict]:
    conn = get_connection()
    try:
        row = conn.execute('SELECT * FROM polls WHERE poll_id = ?', (poll_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_current_poll() -> Optional[Dict]:
    cfg = get_config()
    poll_id = cfg.get('current_poll_id', '')
    if poll_id:
        return get_poll(poll_id)
    # fallback: latest open poll
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM polls WHERE status = 'open' ORDER BY created_at DESC LIMIT 1").fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def set_current_poll(poll_id: str):
    set_config('current_poll_id', poll_id)


def close_poll(poll_id: str):
    conn = get_connection()
    try:
        conn.execute("UPDATE polls SET status = 'closed', closed_at = ? WHERE poll_id = ?", (time.time(), poll_id))
        conn.commit()
    finally:
        conn.close()


def update_poll(poll_id: str, **kwargs):
    allowed = {'title', 'max_rating', 'status'}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return
    set_clause = ', '.join(f'{k} = ?' for k in fields)
    values = list(fields.values()) + [poll_id]
    conn = get_connection()
    try:
        conn.execute(f'UPDATE polls SET {set_clause} WHERE poll_id = ?', values)
        conn.commit()
    finally:
        conn.close()


def list_polls(status: str = None, limit: int = 20) -> List[Dict]:
    conn = get_connection()
    try:
        if status:
            rows = conn.execute('SELECT * FROM polls WHERE status = ? ORDER BY created_at DESC LIMIT ?', (status, limit)).fetchall()
        else:
            rows = conn.execute('SELECT * FROM polls ORDER BY created_at DESC LIMIT ?', (limit,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ──────────────────────────────────────────────────────────────────────
# Vote helpers
# ──────────────────────────────────────────────────────────────────────

def add_vote(poll_id: str, user_id: int, player_id: str, rating: int, batch_id: str = None):
    conn = get_connection()
    try:
        conn.execute('''
            INSERT INTO votes (poll_id, user_id, player_id, rating, batch_id, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (poll_id, user_id, player_id, rating, batch_id, time.time()))
        conn.commit()
    finally:
        conn.close()


def add_votes_batch(poll_id: str, user_id: int, votes: Dict[str, int], batch_id: str = None):
    """Insert multiple votes in one transaction."""
    conn = get_connection()
    try:
        now = time.time()
        for player_id, rating in votes.items():
            conn.execute('''
                INSERT INTO votes (poll_id, user_id, player_id, rating, batch_id, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (poll_id, user_id, player_id, rating, batch_id, now))
        # Update total_votes count in profile
        conn.execute('UPDATE profiles SET total_votes = (SELECT COUNT(*) FROM votes WHERE user_id = ?) WHERE user_id = ?', (user_id, user_id))
        conn.commit()
    finally:
        conn.close()


def has_voted(poll_id: str, user_id: int) -> bool:
    conn = get_connection()
    try:
        row = conn.execute('SELECT 1 FROM votes WHERE poll_id = ? AND user_id = ? LIMIT 1', (poll_id, user_id)).fetchone()
        return row is not None
    finally:
        conn.close()


def get_results(poll_id: str) -> List[Dict]:
    conn = get_connection()
    try:
        rows = conn.execute('''
            SELECT player_id,
                   ROUND(AVG(rating), 2) as avg_rating,
                   COUNT(*) as vote_count
            FROM votes
            WHERE poll_id = ?
            GROUP BY player_id
            ORDER BY avg_rating DESC
        ''', (poll_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_user_vote(poll_id: str, user_id: int) -> Optional[Dict[str, int]]:
    conn = get_connection()
    try:
        rows = conn.execute('SELECT player_id, rating FROM votes WHERE poll_id = ? AND user_id = ?', (poll_id, user_id)).fetchall()
        if not rows:
            return None
        return {r['player_id']: r['rating'] for r in rows}
    finally:
        conn.close()


def get_total_votes_for_poll(poll_id: str) -> int:
    conn = get_connection()
    try:
        row = conn.execute('SELECT COUNT(DISTINCT user_id) as c FROM votes WHERE poll_id = ?', (poll_id,)).fetchone()
        return row['c'] if row else 0
    finally:
        conn.close()


# ──────────────────────────────────────────────────────────────────────
# Admin log helpers
# ──────────────────────────────────────────────────────────────────────

def add_log(admin_user_id: int, action: str, target_user_id: int = None, details: Any = None):
    conn = get_connection()
    try:
        detail_str = json.dumps(details, ensure_ascii=False) if details else None
        conn.execute('''
            INSERT INTO admin_logs (admin_user_id, target_user_id, action, details, timestamp)
            VALUES (?, ?, ?, ?, ?)
        ''', (admin_user_id, target_user_id, action, detail_str, time.time()))
        conn.commit()
    finally:
        conn.close()


def get_logs(limit: int = 50) -> List[Dict]:
    conn = get_connection()
    try:
        rows = conn.execute('''
            SELECT * FROM admin_logs ORDER BY timestamp DESC LIMIT ?
        ''', (limit,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def adjust_vote(poll_id: str, user_id: int, player_id: str, new_rating: int, admin_id: int):
    """Overwrite a user's vote for a player and log the adjustment."""
    conn = get_connection()
    try:
        conn.execute('''
            DELETE FROM votes WHERE poll_id = ? AND user_id = ? AND player_id = ?
        ''', (poll_id, user_id, player_id))
        conn.execute('''
            INSERT INTO votes (poll_id, user_id, player_id, rating, batch_id, timestamp)
            VALUES (?, ?, ?, ?, 'admin_adjust', ?)
        ''', (poll_id, user_id, player_id, new_rating, time.time()))
        conn.commit()
    finally:
        conn.close()
    add_log(admin_id, 'adjust_vote', user_id, {'poll_id': poll_id, 'player_id': player_id, 'new_rating': new_rating})


# ──────────────────────────────────────────────────────────────────────
# Background helpers
# ──────────────────────────────────────────────────────────────────────

def add_background(label: str, url: str, uploaded_by: int, is_default: bool = False):
    conn = get_connection()
    try:
        if is_default:
            conn.execute('UPDATE backgrounds SET is_default = 0')
        conn.execute('''
            INSERT INTO backgrounds (label, url, is_default, uploaded_by, uploaded_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (label, url, int(is_default), uploaded_by, time.time()))
        conn.commit()
    finally:
        conn.close()


def list_backgrounds() -> List[Dict]:
    conn = get_connection()
    try:
        rows = conn.execute('SELECT * FROM backgrounds ORDER BY uploaded_at DESC').fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_default_background() -> Optional[str]:
    conn = get_connection()
    try:
        row = conn.execute('SELECT url FROM backgrounds WHERE is_default = 1').fetchone()
        return row['url'] if row else None
    finally:
        conn.close()


# ──────────────────────────────────────────────────────────────────────
# Prediction helpers
# ──────────────────────────────────────────────────────────────────────

def add_prediction(poll_id: str, user_id: int, player_id: str):
    conn = get_connection()
    try:
        conn.execute('''
            INSERT OR REPLACE INTO predictions (poll_id, user_id, player_id, timestamp)
            VALUES (?, ?, ?, ?)
        ''', (poll_id, user_id, player_id, time.time()))
        conn.commit()
    finally:
        conn.close()


def get_prediction(poll_id: str, user_id: int) -> Optional[Dict]:
    conn = get_connection()
    try:
        row = conn.execute('SELECT * FROM predictions WHERE poll_id = ? AND user_id = ?', (poll_id, user_id)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_predictions_for_poll(poll_id: str) -> List[Dict]:
    conn = get_connection()
    try:
        rows = conn.execute('SELECT * FROM predictions WHERE poll_id = ?', (poll_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def resolve_predictions(poll_id: str, actual_best_player_id: str):
    """Calculate points for predictions. 10 for exact match, 5 for top-3 player."""
    conn = get_connection()
    try:
        # Get top 3 players from results
        top_results = conn.execute('''
            SELECT player_id FROM votes WHERE poll_id = ?
            GROUP BY player_id ORDER BY AVG(rating) DESC LIMIT 3
        ''', (poll_id,)).fetchall()
        top3_ids = [r['player_id'] for r in top_results]

        predictions = conn.execute('SELECT * FROM predictions WHERE poll_id = ?', (poll_id,)).fetchall()
        now = time.time()
        for pred in predictions:
            predicted = pred['player_id']
            if predicted == actual_best_player_id:
                points = 10
                # Award XP for accurate prediction
                add_xp(pred['user_id'], 50, 'accurate_prediction')
            elif predicted in top3_ids:
                points = 5
            else:
                points = 0
            conn.execute('''
                INSERT INTO prediction_results (poll_id, user_id, predicted_player_id, actual_best_player_id, points_earned, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (poll_id, pred['user_id'], predicted, actual_best_player_id, points, now))
        conn.commit()
    finally:
        conn.close()


# ──────────────────────────────────────────────────────────────────────
# Mini-game helpers
# ──────────────────────────────────────────────────────────────────────

def add_mini_game_guess(match_id: str, user_id: int, game_type: str, guess_json: str):
    conn = get_connection()
    try:
        conn.execute('''
            INSERT OR REPLACE INTO mini_games (match_id, user_id, game_type, guess, timestamp)
            VALUES (?, ?, ?, ?, ?)
        ''', (match_id, user_id, game_type, guess_json, time.time()))
        conn.commit()
    finally:
        conn.close()


def get_mini_game_results(match_id: str, user_id: int = None) -> List[Dict]:
    conn = get_connection()
    try:
        if user_id:
            rows = conn.execute('SELECT * FROM mini_games WHERE match_id = ? AND user_id = ?', (match_id, user_id)).fetchall()
        else:
            rows = conn.execute('SELECT * FROM mini_games WHERE match_id = ?', (match_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ──────────────────────────────────────────────────────────────────────
# Referral helpers
# ──────────────────────────────────────────────────────────────────────

def add_referral(referrer_id: int, referred_id: int):
    conn = get_connection()
    try:
        conn.execute('''
            INSERT OR IGNORE INTO referrals (referrer_user_id, referred_user_id, timestamp)
            VALUES (?, ?, ?)
        ''', (referrer_id, referred_id, time.time()))
        conn.commit()
    finally:
        conn.close()


def get_referral_count(user_id: int) -> int:
    conn = get_connection()
    try:
        row = conn.execute('SELECT COUNT(*) as c FROM referrals WHERE referrer_user_id = ?', (user_id,)).fetchone()
        return row['c'] if row else 0
    finally:
        conn.close()


# ──────────────────────────────────────────────────────────────────────
# Notification preferences helpers
# ──────────────────────────────────────────────────────────────────────

def get_notification_prefs(user_id: int) -> Dict:
    conn = get_connection()
    try:
        row = conn.execute('SELECT * FROM notification_prefs WHERE user_id = ?', (user_id,)).fetchone()
        if row:
            return dict(row)
        # Create default prefs
        conn.execute('INSERT INTO notification_prefs (user_id) VALUES (?)', (user_id,))
        conn.commit()
        row = conn.execute('SELECT * FROM notification_prefs WHERE user_id = ?', (user_id,)).fetchone()
        return dict(row)
    finally:
        conn.close()


def set_notification_prefs(user_id: int, **prefs):
    allowed = {'remind_before_close', 'new_poll_notify', 'results_notify'}
    fields = {k: v for k, v in prefs.items() if k in allowed}
    if not fields:
        return
    # Ensure row exists
    get_notification_prefs(user_id)
    set_clause = ', '.join(f'{k} = ?' for k in fields)
    values = list(fields.values()) + [user_id]
    conn = get_connection()
    try:
        conn.execute(f'UPDATE notification_prefs SET {set_clause} WHERE user_id = ?', values)
        conn.commit()
    finally:
        conn.close()


# ──────────────────────────────────────────────────────────────────────
# Re-voting helpers
# ──────────────────────────────────────────────────────────────────────

def delete_user_votes(poll_id: str, user_id: int):
    """Delete all votes for a user in a poll (for re-voting support)."""
    conn = get_connection()
    try:
        conn.execute('DELETE FROM votes WHERE poll_id = ? AND user_id = ?', (poll_id, user_id))
        # Update total_votes count in profile
        conn.execute('UPDATE profiles SET total_votes = (SELECT COUNT(*) FROM votes WHERE user_id = ?) WHERE user_id = ?', (user_id, user_id))
        conn.commit()
    finally:
        conn.close()


# ──────────────────────────────────────────────────────────────────────
# Leaderboard and stats helpers
# ──────────────────────────────────────────────────────────────────────

def get_voter_leaderboard(limit: int = 50) -> List[Dict]:
    """Returns users sorted by total_votes with avg_rating and vote_count."""
    conn = get_connection()
    try:
        rows = conn.execute('''
            SELECT p.user_id, p.username, p.first_name, p.custom_id, p.auto_id, p.avatar,
                   COUNT(DISTINCT v.poll_id) as vote_count,
                   COUNT(v.id) as total_votes,
                   ROUND(AVG(v.rating), 2) as avg_rating
            FROM profiles p
            LEFT JOIN votes v ON v.user_id = p.user_id
            GROUP BY p.user_id
            HAVING total_votes > 0
            ORDER BY total_votes DESC
            LIMIT ?
        ''', (limit,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_season_stats(limit: int = 50) -> List[Dict]:
    """Avg rating per player across all closed polls."""
    conn = get_connection()
    try:
        rows = conn.execute('''
            SELECT v.player_id,
                   pl.name as player_name,
                   pl.photo_url,
                   ROUND(AVG(v.rating), 2) as avg_rating,
                   COUNT(DISTINCT v.poll_id) as matches_rated,
                   COUNT(v.id) as total_ratings
            FROM votes v
            JOIN polls po ON po.poll_id = v.poll_id AND po.status = 'closed'
            LEFT JOIN players pl ON pl.player_id = v.player_id
            GROUP BY v.player_id
            ORDER BY avg_rating DESC
            LIMIT ?
        ''', (limit,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_player_history(player_id: str) -> List[Dict]:
    """Match-by-match ratings for a player."""
    conn = get_connection()
    try:
        rows = conn.execute('''
            SELECT v.poll_id,
                   po.title as match_title,
                   po.created_at,
                   po.closed_at,
                   ROUND(AVG(v.rating), 2) as avg_rating,
                   COUNT(v.id) as vote_count
            FROM votes v
            JOIN polls po ON po.poll_id = v.poll_id
            WHERE v.player_id = ?
            GROUP BY v.poll_id
            ORDER BY po.created_at DESC
        ''', (player_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_all_polls_stats() -> Dict:
    """Returns best match (highest avg) and worst match (lowest avg) across all polls."""
    conn = get_connection()
    try:
        best = conn.execute('''
            SELECT po.poll_id, po.title, ROUND(AVG(v.rating), 2) as avg_rating,
                   COUNT(DISTINCT v.user_id) as total_voters
            FROM votes v
            JOIN polls po ON po.poll_id = v.poll_id AND po.status = 'closed'
            GROUP BY po.poll_id
            ORDER BY avg_rating DESC
            LIMIT 1
        ''').fetchone()
        worst = conn.execute('''
            SELECT po.poll_id, po.title, ROUND(AVG(v.rating), 2) as avg_rating,
                   COUNT(DISTINCT v.user_id) as total_voters
            FROM votes v
            JOIN polls po ON po.poll_id = v.poll_id AND po.status = 'closed'
            GROUP BY po.poll_id
            ORDER BY avg_rating ASC
            LIMIT 1
        ''').fetchone()
        return {
            'best_match': dict(best) if best else None,
            'worst_match': dict(worst) if worst else None,
        }
    finally:
        conn.close()


# ──────────────────────────────────────────────────────────────────────
# XP / Level helpers
# ──────────────────────────────────────────────────────────────────────

_LEVEL_THRESHOLDS = [
    (1500, 'Легенда Стэмфорд Бридж'),
    (500,  'Ультрас'),
    (100,  'Фанат'),
    (0,    'Новичок'),
]


def _calc_level(total_xp: int) -> str:
    for threshold, name in _LEVEL_THRESHOLDS:
        if total_xp >= threshold:
            return name
    return 'Новичок'


def add_xp(user_id: int, amount: int, reason: str = None):
    """Add XP to a user, update total and recalculate level."""
    conn = get_connection()
    try:
        conn.execute('''
            INSERT INTO xp_log (user_id, amount, reason, timestamp)
            VALUES (?, ?, ?, ?)
        ''', (user_id, amount, reason, time.time()))
        # Get current total
        row = conn.execute('SELECT total_xp FROM user_xp WHERE user_id = ?', (user_id,)).fetchone()
        if row:
            new_total = row['total_xp'] + amount
        else:
            new_total = amount
        level = _calc_level(new_total)
        conn.execute('''
            INSERT OR REPLACE INTO user_xp (user_id, total_xp, level)
            VALUES (?, ?, ?)
        ''', (user_id, new_total, level))
        conn.commit()
    finally:
        conn.close()


def get_user_xp(user_id: int) -> Dict:
    """Return XP data: total_xp, level, xp_to_next_level, progress_pct."""
    conn = get_connection()
    try:
        row = conn.execute('SELECT total_xp, level FROM user_xp WHERE user_id = ?', (user_id,)).fetchone()
        if not row:
            return {'total_xp': 0, 'level': 'Новичок', 'xp_to_next_level': 100, 'progress_pct': 0}
        total_xp = row['total_xp']
        level = row['level']
        # Calculate progress within current level
        if total_xp >= 1500:
            xp_to_next = 0
            progress_pct = 100
        elif total_xp >= 500:
            xp_to_next = 1500 - total_xp
            progress_pct = int((total_xp - 500) * 100 / (1500 - 500))
        elif total_xp >= 100:
            xp_to_next = 500 - total_xp
            progress_pct = int((total_xp - 100) * 100 / (500 - 100))
        else:
            xp_to_next = 100 - total_xp
            progress_pct = int(total_xp * 100 / 100)
        return {
            'total_xp': total_xp,
            'level': level,
            'xp_to_next_level': xp_to_next,
            'progress_pct': min(100, max(0, progress_pct)),
        }
    finally:
        conn.close()


# ──────────────────────────────────────────────────────────────────────
# Streak helpers
# ──────────────────────────────────────────────────────────────────────

def get_user_streak(user_id: int) -> Dict:
    """Return streak data: current_streak, max_streak."""
    conn = get_connection()
    try:
        row = conn.execute('SELECT current_streak, max_streak FROM streaks WHERE user_id = ?', (user_id,)).fetchone()
        if not row:
            return {'current_streak': 0, 'max_streak': 0}
        return {'current_streak': row['current_streak'], 'max_streak': row['max_streak']}
    finally:
        conn.close()


def update_streak(user_id: int, poll_id: str):
    """Update streak based on whether user voted in consecutive polls."""
    conn = get_connection()
    try:
        # Get current streak row
        row = conn.execute('SELECT current_streak, max_streak, last_vote_poll_id FROM streaks WHERE user_id = ?', (user_id,)).fetchone()

        # Find the poll before this one (by created_at order)
        prev_poll = conn.execute('''
            SELECT poll_id FROM polls
            WHERE created_at < (SELECT created_at FROM polls WHERE poll_id = ?)
            ORDER BY created_at DESC
            LIMIT 1
        ''', (poll_id,)).fetchone()

        if row:
            last_poll = row['last_vote_poll_id']
            current_streak = row['current_streak']
            max_streak = row['max_streak']

            if last_poll == poll_id:
                # Already counted this poll
                return

            if prev_poll and last_poll == prev_poll['poll_id']:
                # Voted in the previous poll - increment streak
                current_streak += 1
            else:
                # Missed a poll or first vote - reset to 1
                current_streak = 1

            if current_streak > max_streak:
                max_streak = current_streak

            conn.execute('''
                UPDATE streaks SET current_streak = ?, max_streak = ?, last_vote_poll_id = ?
                WHERE user_id = ?
            ''', (current_streak, max_streak, poll_id, user_id))
        else:
            # First ever vote
            conn.execute('''
                INSERT INTO streaks (user_id, current_streak, max_streak, last_vote_poll_id)
                VALUES (?, 1, 1, ?)
            ''', (user_id, poll_id))

        conn.commit()
    finally:
        conn.close()


# ──────────────────────────────────────────────────────────────────────
# Match events helpers
# ──────────────────────────────────────────────────────────────────────

def save_match_events(match_id: str, events: List[Dict]):
    """Save match events (goals, cards, substitutions). INSERT OR IGNORE to avoid dupes."""
    conn = get_connection()
    try:
        for ev in events:
            conn.execute('''
                INSERT OR IGNORE INTO match_events (match_id, player_id, event_type, minute, detail)
                VALUES (?, ?, ?, ?, ?)
            ''', (match_id, ev.get('player_id'), ev.get('event_type'), ev.get('minute'), ev.get('detail')))
        conn.commit()
    finally:
        conn.close()


def get_match_events(match_id: str) -> List[Dict]:
    """Return all events for a match, ordered by minute."""
    conn = get_connection()
    try:
        rows = conn.execute(
            'SELECT * FROM match_events WHERE match_id = ? ORDER BY minute',
            (match_id,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ──────────────────────────────────────────────────────────────────────
# AI ratings helpers
# ──────────────────────────────────────────────────────────────────────

def save_ai_ratings(match_id: str, ratings: List[Dict]):
    """Save AI (sstats) ratings for players. INSERT OR REPLACE to update."""
    conn = get_connection()
    try:
        for r in ratings:
            conn.execute('''
                INSERT OR REPLACE INTO ai_ratings (match_id, player_id, sstats_rating, normalized_rating)
                VALUES (?, ?, ?, ?)
            ''', (match_id, r.get('player_id'), r.get('sstats_rating'), r.get('normalized_rating')))
        conn.commit()
    finally:
        conn.close()


def get_ai_ratings(match_id: str) -> List[Dict]:
    """Return AI ratings for all players in a match."""
    conn = get_connection()
    try:
        rows = conn.execute(
            'SELECT * FROM ai_ratings WHERE match_id = ? ORDER BY normalized_rating DESC',
            (match_id,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ──────────────────────────────────────────────────────────────────────
# Challenge helpers
# ──────────────────────────────────────────────────────────────────────

def create_challenge(title: str, description: str, challenge_type: str, target: int,
                     reward_xp: int = 20, start_time: float = None, end_time: float = None,
                     created_by: int = None) -> int:
    """Create a new challenge and return its id."""
    conn = get_connection()
    try:
        now = time.time()
        cur = conn.execute('''
            INSERT INTO challenges (title, description, type, target, reward_xp, start_time, end_time, active, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
        ''', (title, description, challenge_type, target, reward_xp,
              start_time or now, end_time, created_by))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_active_challenges() -> List[Dict]:
    """Return all active challenges."""
    conn = get_connection()
    try:
        rows = conn.execute(
            'SELECT * FROM challenges WHERE active = 1 ORDER BY id DESC'
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_all_challenges(include_inactive: bool = False) -> List[Dict]:
    """Return all challenges, optionally including inactive ones."""
    conn = get_connection()
    try:
        if include_inactive:
            rows = conn.execute('SELECT * FROM challenges ORDER BY id DESC').fetchall()
        else:
            rows = conn.execute('SELECT * FROM challenges WHERE active = 1 ORDER BY id DESC').fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_user_challenge_progress(user_id: int) -> List[Dict]:
    """Return challenge progress for a user across all active challenges."""
    conn = get_connection()
    try:
        rows = conn.execute('''
            SELECT cp.*, c.title, c.description, c.type, c.target, c.reward_xp, c.end_time
            FROM challenge_progress cp
            JOIN challenges c ON c.id = cp.challenge_id
            WHERE cp.user_id = ? AND c.active = 1
            ORDER BY cp.completed ASC, c.id DESC
        ''', (user_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def update_challenge_progress(user_id: int, challenge_id: int, increment: int = 1):
    """Increment challenge progress for user. Creates row if not exists."""
    conn = get_connection()
    try:
        row = conn.execute(
            'SELECT progress, completed FROM challenge_progress WHERE user_id = ? AND challenge_id = ?',
            (user_id, challenge_id)
        ).fetchone()
        if row:
            if row['completed']:
                return  # already completed
            new_progress = row['progress'] + increment
            conn.execute(
                'UPDATE challenge_progress SET progress = ? WHERE user_id = ? AND challenge_id = ?',
                (new_progress, user_id, challenge_id)
            )
        else:
            conn.execute(
                'INSERT INTO challenge_progress (user_id, challenge_id, progress) VALUES (?, ?, ?)',
                (user_id, challenge_id, increment)
            )
        conn.commit()
    finally:
        conn.close()


def complete_challenge(user_id: int, challenge_id: int):
    """Mark a challenge as completed for the user and award XP."""
    conn = get_connection()
    try:
        conn.execute(
            'UPDATE challenge_progress SET completed = 1, completed_at = ? WHERE user_id = ? AND challenge_id = ?',
            (time.time(), user_id, challenge_id)
        )
        conn.commit()
    finally:
        conn.close()
    # Get reward XP
    conn = get_connection()
    try:
        row = conn.execute('SELECT reward_xp FROM challenges WHERE id = ?', (challenge_id,)).fetchone()
        if row:
            add_xp(user_id, row['reward_xp'], 'challenge_complete')
    finally:
        conn.close()


def get_challenge_by_id(challenge_id: int) -> Optional[Dict]:
    """Return a single challenge by id."""
    conn = get_connection()
    try:
        row = conn.execute('SELECT * FROM challenges WHERE id = ?', (challenge_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def toggle_challenge(challenge_id: int, active: bool):
    """Activate or deactivate a challenge."""
    conn = get_connection()
    try:
        conn.execute('UPDATE challenges SET active = ? WHERE id = ?', (int(active), challenge_id))
        conn.commit()
    finally:
        conn.close()


# ──────────────────────────────────────────────────────────────────────
# Award helpers
# ──────────────────────────────────────────────────────────────────────

def save_award(user_id: int, award_type: str, month: str, details: dict = None):
    """Save an award. details is stored as JSON string."""
    conn = get_connection()
    try:
        year = int(month.split('-')[0]) if '-' in month else 0
        details_json = json.dumps(details, ensure_ascii=False) if details else None
        conn.execute('''
            INSERT OR IGNORE INTO awards (user_id, award_type, month, year, details, awarded_at)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (user_id, award_type, month, year, details_json, time.time()))
        conn.commit()
    finally:
        conn.close()


def get_user_awards(user_id: int) -> List[Dict]:
    """Return all awards for a user, newest first."""
    conn = get_connection()
    try:
        rows = conn.execute(
            'SELECT * FROM awards WHERE user_id = ? ORDER BY awarded_at DESC',
            (user_id,)
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            if d.get('details'):
                try:
                    d['details'] = json.loads(d['details'])
                except (json.JSONDecodeError, TypeError):
                    pass
            result.append(d)
        return result
    finally:
        conn.close()


def get_month_awards(month: str) -> List[Dict]:
    """Return all awards for a given month (YYYY-MM format)."""
    conn = get_connection()
    try:
        rows = conn.execute(
            'SELECT * FROM awards WHERE month = ? ORDER BY award_type',
            (month,)
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            if d.get('details'):
                try:
                    d['details'] = json.loads(d['details'])
                except (json.JSONDecodeError, TypeError):
                    pass
            result.append(d)
        return result
    finally:
        conn.close()


def get_all_awards(limit: int = 50) -> List[Dict]:
    """Return all awards, newest first."""
    conn = get_connection()
    try:
        rows = conn.execute(
            'SELECT * FROM awards ORDER BY awarded_at DESC LIMIT ?',
            (limit,)
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            if d.get('details'):
                try:
                    d['details'] = json.loads(d['details'])
                except (json.JSONDecodeError, TypeError):
                    pass
            result.append(d)
        return result
    finally:
        conn.close()


# ──────────────────────────────────────────────────────────────────────
# FPL helpers
# ──────────────────────────────────────────────────────────────────────

def save_fpl_points(player_name: str, player_id: str = None, match_id: str = None,
                    fpl_points: int = 0, gameweek: int = 0, fpl_player_id: int = None):
    """Save FPL points for a player."""
    conn = get_connection()
    try:
        conn.execute('''
            INSERT INTO fpl_points (player_name, player_id, match_id, fpl_points, gameweek, fpl_player_id, cached_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (player_name, player_id, match_id, fpl_points, gameweek, fpl_player_id, time.time()))
        conn.commit()
    finally:
        conn.close()


def get_fpl_points_for_match(match_id: str) -> List[Dict]:
    """Return all FPL points records for a given match."""
    conn = get_connection()
    try:
        rows = conn.execute(
            'SELECT * FROM fpl_points WHERE match_id = ? ORDER BY fpl_points DESC',
            (match_id,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_fpl_cache(key: str) -> Optional[Dict]:
    """Get cached FPL data by key. Returns dict with 'data' (parsed JSON) and 'cached_at'."""
    conn = get_connection()
    try:
        row = conn.execute('SELECT data, cached_at FROM fpl_cache WHERE key = ?', (key,)).fetchone()
        if not row:
            return None
        return {'data': json.loads(row['data']), 'cached_at': row['cached_at']}
    finally:
        conn.close()


def set_fpl_cache(key: str, data):
    """Set FPL cache entry. data will be JSON-serialized."""
    conn = get_connection()
    try:
        data_str = json.dumps(data, ensure_ascii=False)
        conn.execute('''
            INSERT OR REPLACE INTO fpl_cache (key, data, cached_at)
            VALUES (?, ?, ?)
        ''', (key, data_str, time.time()))
        conn.commit()
    finally:
        conn.close()


# ──────────────────────────────────────────────────────────────────────
# Match Analytics helpers
# ──────────────────────────────────────────────────────────────────────

def save_match_analytics(match_id: str, poll_id: str, data_dict: Dict):
    """Save pre-match analytics data."""
    conn = get_connection()
    try:
        conn.execute('''
            INSERT OR REPLACE INTO match_analytics
            (match_id, poll_id, opponent_name, opponent_id, opponent_form, h2h_stats, predicted_result, analytics_data, generated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            match_id,
            poll_id,
            data_dict.get('opponent_name'),
            data_dict.get('opponent_id'),
            json.dumps(data_dict.get('opponent_form'), ensure_ascii=False) if data_dict.get('opponent_form') else None,
            json.dumps(data_dict.get('h2h_stats'), ensure_ascii=False) if data_dict.get('h2h_stats') else None,
            data_dict.get('predicted_result'),
            json.dumps(data_dict.get('analytics_data'), ensure_ascii=False) if data_dict.get('analytics_data') else None,
            time.time()
        ))
        conn.commit()
    finally:
        conn.close()


def get_match_analytics(match_id: str) -> Optional[Dict]:
    """Get pre-match analytics by match_id."""
    conn = get_connection()
    try:
        row = conn.execute('SELECT * FROM match_analytics WHERE match_id = ?', (match_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        if d.get('opponent_form'):
            try:
                d['opponent_form'] = json.loads(d['opponent_form'])
            except (json.JSONDecodeError, TypeError):
                pass
        if d.get('h2h_stats'):
            try:
                d['h2h_stats'] = json.loads(d['h2h_stats'])
            except (json.JSONDecodeError, TypeError):
                pass
        if d.get('analytics_data'):
            try:
                d['analytics_data'] = json.loads(d['analytics_data'])
            except (json.JSONDecodeError, TypeError):
                pass
        return d
    finally:
        conn.close()


def get_analytics_by_poll(poll_id: str) -> Optional[Dict]:
    """Get pre-match analytics by poll_id."""
    conn = get_connection()
    try:
        row = conn.execute('SELECT * FROM match_analytics WHERE poll_id = ?', (poll_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        if d.get('opponent_form'):
            try:
                d['opponent_form'] = json.loads(d['opponent_form'])
            except (json.JSONDecodeError, TypeError):
                pass
        if d.get('h2h_stats'):
            try:
                d['h2h_stats'] = json.loads(d['h2h_stats'])
            except (json.JSONDecodeError, TypeError):
                pass
        if d.get('analytics_data'):
            try:
                d['analytics_data'] = json.loads(d['analytics_data'])
            except (json.JSONDecodeError, TypeError):
                pass
        return d
    finally:
        conn.close()


# ──────────────────────────────────────────────────────────────────────
# Match Report helpers
# ──────────────────────────────────────────────────────────────────────

def save_match_report(poll_id: str, match_id: str, report_text: str, report_data: Dict):
    """Save a generated match report."""
    conn = get_connection()
    try:
        data_json = json.dumps(report_data, ensure_ascii=False) if report_data else None
        conn.execute('''
            INSERT OR REPLACE INTO match_reports (poll_id, match_id, report_text, report_data, generated_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (poll_id, match_id, report_text, data_json, time.time()))
        conn.commit()
    finally:
        conn.close()


def get_match_report(poll_id: str) -> Optional[Dict]:
    """Return the match report for a poll."""
    conn = get_connection()
    try:
        row = conn.execute('SELECT * FROM match_reports WHERE poll_id = ?', (poll_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        if d.get('report_data'):
            try:
                d['report_data'] = json.loads(d['report_data'])
            except (json.JSONDecodeError, TypeError):
                pass
        return d
    finally:
        conn.close()
