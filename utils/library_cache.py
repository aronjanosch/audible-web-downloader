import json
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
