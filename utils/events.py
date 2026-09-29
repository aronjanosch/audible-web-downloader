"""Small append-only activity log for the household overview (additive table)."""

import time

from utils.db import get_db


def record_event(account_name, kind, detail=None):
    """Best effort: an activity entry must never break the operation it describes."""
    try:
        conn = get_db()
        conn.execute(
            "INSERT INTO account_events (account_name, kind, detail, created_at) VALUES (?,?,?,?)",
            (account_name, kind, detail, time.time()),
        )
        conn.commit()
    except Exception:
        pass


def last_event_time(account_name, kind):
    row = get_db().execute(
        "SELECT MAX(created_at) AS t FROM account_events WHERE account_name=? AND kind=?",
        (account_name, kind),
    ).fetchone()
    return row["t"] if row else None


def record_duplicate_avoided(account_name, asin, title=None):
    """Log that a title was not downloaded again because the household already has it.

    One event per (account, asin): repeated polls or repeated skips of the same
    title must not inflate the counter.
    """
    try:
        conn = get_db()
        detail = f"{asin}|{title or ''}"
        exists = conn.execute(
            "SELECT 1 FROM account_events WHERE account_name=? AND kind='duplicate_avoided' "
            "AND detail LIKE ? LIMIT 1",
            (account_name, f"{asin}|%"),
        ).fetchone()
        if exists:
            return False
        conn.execute(
            "INSERT INTO account_events (account_name, kind, detail, created_at) VALUES (?,?,?,?)",
            (account_name, 'duplicate_avoided', detail, time.time()),
        )
        conn.commit()
        return True
    except Exception:
        return False


def duplicates_avoided_since(seconds):
    row = get_db().execute(
        "SELECT COUNT(*) AS n FROM account_events WHERE kind='duplicate_avoided' AND created_at >= ?",
        (time.time() - seconds,),
    ).fetchone()
    return row["n"] if row else 0
