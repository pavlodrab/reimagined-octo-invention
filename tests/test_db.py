"""
Tests for db.py helpers — upsert, insert_ignore, lastrowid path (PR #3).
Run on the SQLite driver path; the Postgres path uses the same helpers
but with ON CONFLICT semantics translated by _translate_sql.
"""


def test_upsert_inserts_then_updates(db_module):
    """_upsert should INSERT on first call and REPLACE on second."""
    conn = db_module.get_connection()
    try:
        db_module._upsert(conn, "config",
                          {"key": "test_pr10_a", "value": "v1"},
                          conflict_cols=["key"])
        db_module._upsert(conn, "config",
                          {"key": "test_pr10_a", "value": "v2"},
                          conflict_cols=["key"])
        conn.commit()
        row = conn.execute(
            "SELECT value FROM config WHERE key = ?",
            ("test_pr10_a",),
        ).fetchone()
        assert row["value"] == "v2"
    finally:
        conn.close()


def test_insert_ignore_keeps_first_on_conflict(db_module):
    """_insert_ignore should preserve the first-written value."""
    conn = db_module.get_connection()
    try:
        db_module._insert_ignore(conn, "config",
                                 {"key": "test_pr10_b", "value": "first"},
                                 conflict_cols=["key"])
        db_module._insert_ignore(conn, "config",
                                 {"key": "test_pr10_b", "value": "second"},
                                 conflict_cols=["key"])
        conn.commit()
        row = conn.execute(
            "SELECT value FROM config WHERE key = ?",
            ("test_pr10_b",),
        ).fetchone()
        assert row["value"] == "first"
    finally:
        conn.close()


def test_create_challenge_returns_id(db_module):
    """create_challenge uses _insert_and_get_id — verify it returns a
    real, monotonically increasing primary key."""
    cid1 = db_module.create_challenge("Ch1", "desc", "custom", 1, reward_xp=5)
    cid2 = db_module.create_challenge("Ch2", "desc", "custom", 1, reward_xp=5)
    assert cid1 > 0
    assert cid2 > cid1


def test_add_admin_idempotent(db_module):
    """add_admin uses _upsert on (user_id) — second call updates username."""
    db_module.add_admin(99001, "first_name", added_by=1)
    db_module.add_admin(99001, "updated_name", added_by=1)
    admins = db_module.list_admins()
    matching = [a for a in admins if a["user_id"] == 99001]
    assert len(matching) == 1
    assert matching[0]["username"] == "updated_name"


def test_add_referral_keeps_first_referrer(db_module):
    """add_referral uses _insert_ignore on (referred_user_id). When two
    different referrers claim the same referee, the first wins."""
    db_module.add_referral(referrer_id=10001, referred_id=20001)
    db_module.add_referral(referrer_id=10002, referred_id=20001)  # ignored
    conn = db_module.get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM referrals WHERE referred_user_id = ?",
            (20001,),
        ).fetchall()
    finally:
        conn.close()
    assert len(rows) == 1
    assert rows[0]["referrer_user_id"] == 10001


def test_init_db_is_idempotent(db_module):
    """Running init_db a second time must not raise (e.g. ALTER TABLE
    handling, CREATE TABLE IF NOT EXISTS)."""
    # Should be a no-op the second time around
    db_module.init_db()
    db_module.init_db()
