import json
import threading
import time

from utils.db import get_db

CACHE_TTL_SECONDS = 6 * 3600


def get_cached_library(account_name: str) -> list | None:
    """Return cached book list if fresh, else None. Never raises."""
    try:
        row = get_db().execute(
            "SELECT books_json, fetched_at FROM library_cache WHERE account_name = ?",
            (account_name,)
        ).fetchone()
        if row is None:
            return None
        if time.time() - row['fetched_at'] > CACHE_TTL_SECONDS:
            return None
        return json.loads(row['books_json'])
    except Exception:
        return None


def write_library_cache(account_name: str, books: list) -> None:
    """Upsert books list into cache. Silently swallows errors."""
    try:
        conn = get_db()
        conn.execute(
            """
            INSERT INTO library_cache (account_name, fetched_at, books_json)
            VALUES (?, ?, ?)
            ON CONFLICT(account_name) DO UPDATE SET
                fetched_at = excluded.fetched_at,
                books_json = excluded.books_json
            """,
            (account_name, time.time(), json.dumps(books))
        )
        conn.commit()
    except Exception:
        pass


def invalidate_cache(account_name: str) -> None:
    """Delete cache entry for account, silently if missing."""
    try:
        conn = get_db()
        conn.execute("DELETE FROM library_cache WHERE account_name = ?", (account_name,))
        conn.commit()
    except Exception:
        pass


# ── merged /api/library/all response cache ──
# The merged household catalog is a pure function of each account's cached library, so it is keyed
# by (account, cache write time). Any refetch, invalidation or expiry changes the key; nothing needs
# explicit invalidation. Bounded so a household with many member-scoped views cannot grow it.
_MERGED_MAX = 8
_merged: dict[tuple, bytes] = {}
_merged_lock = threading.Lock()


def cache_stamp(account_name: str) -> float | None:
    """fetched_at of a fresh cache entry without parsing the (large) JSON payload, else None."""
    try:
        row = get_db().execute(
            "SELECT fetched_at FROM library_cache WHERE account_name = ?", (account_name,)).fetchone()
    except Exception:
        return None
    if row is None or time.time() - row['fetched_at'] > CACHE_TTL_SECONDS:
        return None
    return row['fetched_at']


def merged_get(key: tuple) -> bytes | None:
    with _merged_lock:
        return _merged.get(key)


def merged_put(key: tuple, body: bytes) -> None:
    with _merged_lock:
        _merged.pop(key, None)
        _merged[key] = body
        while len(_merged) > _MERGED_MAX:
            _merged.pop(next(iter(_merged)))
