"""
SQLite database layer for Audible Web Downloader.

Replaces the scattered JSON files with a single audible.db file.
Provides thread-local connections, WAL mode for concurrency, and
a one-time migration from existing JSON config files.

Schema version history:
  1 — initial schema (accounts, libraries, books, download_queue,
                       download_batches, auto_download_rules, scan_cache)
  2 — added library_cache table
  3 — dropped download_queue and download_batches (queue is now in-memory only)
"""

import json
import logging
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

logger = logging.getLogger(__name__)

# Module-level state
_db_path: Optional[Path] = None
_local = threading.local()

SCHEMA_VERSION = 3

_SCHEMA_DDL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS accounts (
    name                     TEXT PRIMARY KEY,
    region                   TEXT NOT NULL,
    authenticated            INTEGER NOT NULL DEFAULT 0,
    auto_dl_enabled          INTEGER NOT NULL DEFAULT 0,
    auto_dl_interval_hours   INTEGER NOT NULL DEFAULT 6,
    auto_dl_default_library  TEXT,
    auto_dl_last_run         TEXT,
    auto_dl_last_run_result  TEXT,
    pending_invitation_token TEXT
);

CREATE TABLE IF NOT EXISTS auto_download_rules (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    account_name TEXT NOT NULL REFERENCES accounts(name) ON DELETE CASCADE,
    position     INTEGER NOT NULL,
    field        TEXT NOT NULL,
    value        TEXT NOT NULL,
    library_name TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_adr_account ON auto_download_rules(account_name, position);

CREATE TABLE IF NOT EXISTS libraries (
    name       TEXT PRIMARY KEY,
    path       TEXT NOT NULL UNIQUE,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS books (
    asin                  TEXT PRIMARY KEY,
    title                 TEXT NOT NULL,
    authors               TEXT,
    series                TEXT,
    narrator              TEXT,
    publisher             TEXT,
    language              TEXT,
    runtime_length_min    INTEGER,
    status                TEXT NOT NULL DEFAULT 'wanted'
        CHECK (status IN ('wanted','downloading','downloaded','missing','ignored')),
    file_path             TEXT,
    file_size_bytes       INTEGER,
    last_seen_on_disk     REAL,
    library_name          TEXT REFERENCES libraries(name) ON DELETE SET NULL,
    downloaded_by_account TEXT REFERENCES accounts(name) ON DELETE SET NULL,
    added_at              REAL NOT NULL,
    updated_at            REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_books_status  ON books(status);
CREATE INDEX IF NOT EXISTS idx_books_library ON books(library_name);

CREATE TABLE IF NOT EXISTS scan_cache (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    library_name TEXT NOT NULL REFERENCES libraries(name) ON DELETE CASCADE,
    file_path    TEXT NOT NULL UNIQUE,
    asin         TEXT,
    title        TEXT,
    authors      TEXT,
    series       TEXT,
    narrator     TEXT,
    year         TEXT,
    language     TEXT,
    file_size    INTEGER,
    duration_sec REAL,
    last_scanned REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_scan_library ON scan_cache(library_name);
CREATE INDEX IF NOT EXISTS idx_scan_asin    ON scan_cache(asin) WHERE asin IS NOT NULL;

CREATE TABLE IF NOT EXISTS library_cache (
    account_name TEXT PRIMARY KEY REFERENCES accounts(name) ON DELETE CASCADE,
    fetched_at   REAL NOT NULL,
    books_json   TEXT NOT NULL
);
"""


def init_db(db_path: Path) -> None:
    """
    Set the database path. Call once from create_app() before any request.

    Args:
        db_path: Absolute path to the SQLite database file.
    """
    global _db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    _db_path = db_path


def get_db() -> sqlite3.Connection:
    """
    Return the thread-local SQLite connection, creating it if needed.

    Uses WAL journal mode and returns rows as sqlite3.Row objects
    (accessible by column name like dicts).
    """
    if _db_path is None:
        raise RuntimeError("Database not initialised — call init_db() first")

    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(str(_db_path), check_same_thread=False, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        # Wait up to 30s when another thread/request holds the write lock (large batches + SSE, etc.)
        conn.execute("PRAGMA busy_timeout=30000")
        _local.conn = conn
    return conn


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    """
    Context manager that wraps statements in an explicit transaction.

    Commits on success, rolls back on any exception.

    Usage::

        with transaction() as conn:
            conn.execute("INSERT INTO ...")
            conn.execute("UPDATE ...")
    """
    conn = get_db()
    try:
        conn.execute("BEGIN")
        yield conn
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


# ---------------------------------------------------------------------------
# Schema creation and JSON → SQLite migration
# ---------------------------------------------------------------------------

def migrate() -> None:
    """
    Ensure the database schema is at the current version.

    Idempotent: if PRAGMA user_version already equals SCHEMA_VERSION,
    this function returns immediately without touching anything.

    On a fresh database (user_version == 0):
      1. Creates all tables and indexes.
      2. Imports data from any existing JSON config files.
      3. Sets PRAGMA user_version = SCHEMA_VERSION.

    All work is done in a single transaction so any failure rolls back
    completely; the JSON files are left untouched as a backup.
    """
    conn = get_db()
    current_version = conn.execute("PRAGMA user_version").fetchone()[0]

    if current_version >= SCHEMA_VERSION:
        logger.info("Database schema already at version %d — skipping migration", current_version)
        return

    logger.info("Running database migration %d → %d ...", current_version, SCHEMA_VERSION)

    try:
        if current_version == 0:
            # Fresh install: create all tables and import from JSON files
            conn.executescript(_SCHEMA_DDL)
            with transaction() as conn:
                _migrate_accounts(conn)
                _migrate_libraries(conn)
                _migrate_books(conn)
                _migrate_scan_cache(conn)

        if current_version < 2:
            # v1 → v2: add library_cache table
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS library_cache (
                    account_name TEXT PRIMARY KEY REFERENCES accounts(name) ON DELETE CASCADE,
                    fetched_at   REAL NOT NULL,
                    books_json   TEXT NOT NULL
                );
            """)

        if current_version < 3:
            # v2 → v3: drop ephemeral download tables (queue is now in-memory only)
            conn.execute("DROP TABLE IF EXISTS download_queue")
            conn.execute("DROP TABLE IF EXISTS download_batches")

        # user_version cannot be set inside a normal transaction via parameter binding
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        logger.info("Database migration complete (version %d)", SCHEMA_VERSION)

        # Always reset books that were left in 'downloading' state — they can only
        # reach that state via an active request and won't survive a process restart.
        stale = conn.execute(
            "UPDATE books SET status='wanted', updated_at=? WHERE status='downloading'",
            (time.time(),)
        ).rowcount
        if stale:
            logger.info("Reset %d stale 'downloading' book(s) to 'wanted'", stale)

    except Exception as e:
        logger.error("Database migration failed: %s", e)
        raise


def _load_json(path: Path) -> dict:
    """Load a JSON file, returning {} if missing or corrupt."""
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, IOError) as e:
        logger.warning("Could not read %s for migration: %s", path, e)
        return {}


def _migrate_accounts(conn: sqlite3.Connection) -> None:
    """Import config/accounts.json → accounts + auto_download_rules."""
    from utils.constants import ACCOUNTS_FILE
    accounts = _load_json(ACCOUNTS_FILE)

    for name, data in accounts.items():
        if not isinstance(data, dict):
            continue
        auto_dl = data.get("auto_download") or {}
        conn.execute(
            """
            INSERT OR IGNORE INTO accounts
                (name, region, authenticated,
                 auto_dl_enabled, auto_dl_interval_hours,
                 auto_dl_default_library,
                 auto_dl_last_run, auto_dl_last_run_result,
                 pending_invitation_token)
            VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (
                name,
                data.get("region", "us"),
                1 if data.get("authenticated") else 0,
                1 if auto_dl.get("enabled") else 0,
                auto_dl.get("interval_hours", 6),
                auto_dl.get("default_library_name"),
                auto_dl.get("last_run"),
                auto_dl.get("last_run_result"),
                data.get("pending_invitation_token"),
            ),
        )

        # Import ordered rules list
        for position, rule in enumerate(auto_dl.get("rules") or []):
            if not isinstance(rule, dict):
                continue
            conn.execute(
                """
                INSERT OR IGNORE INTO auto_download_rules
                    (account_name, position, field, value, library_name)
                VALUES (?,?,?,?,?)
                """,
                (name, position, rule.get("field", ""), rule.get("value", ""), rule.get("library_name", "")),
            )

    logger.info("Migrated %d accounts", len(accounts))


def _migrate_libraries(conn: sqlite3.Connection) -> None:
    """Import config/libraries.json → libraries."""
    from utils.constants import LIBRARIES_FILE
    libraries = _load_json(LIBRARIES_FILE)

    for name, data in libraries.items():
        if not isinstance(data, dict):
            continue
        # created may be an ISO string; store as unix timestamp if possible
        created_raw = data.get("created_at") or data.get("created", "")
        created_at = _parse_timestamp(created_raw)
        conn.execute(
            "INSERT OR IGNORE INTO libraries (name, path, created_at) VALUES (?,?,?)",
            (name, data.get("path", ""), created_at),
        )

    logger.info("Migrated %d libraries", len(libraries))


def _migrate_books(conn: sqlite3.Connection) -> None:
    """Import config/library.json → books."""
    from utils.constants import CONFIG_DIR
    library_file = CONFIG_DIR / "library.json"
    books = _load_json(library_file)

    now = time.time()
    count = 0
    for asin, data in books.items():
        if not isinstance(data, dict) or asin.startswith("_"):
            continue
        # Old state='converted' → status='downloaded'; anything else → 'wanted'
        old_state = data.get("state", "")
        status = "downloaded" if old_state == "converted" else "wanted"
        conn.execute(
            """
            INSERT OR IGNORE INTO books
                (asin, title, status, file_path,
                 library_name, downloaded_by_account,
                 added_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            (
                asin,
                data.get("title", ""),
                status,
                data.get("file_path"),
                data.get("library_name"),
                data.get("downloaded_by_account"),
                data.get("timestamp", now),
                now,
            ),
        )
        count += 1

    logger.info("Migrated %d books", count)


def _migrate_scan_cache(conn: sqlite3.Connection) -> None:
    """Import library_data/libraries.json → scan_cache."""
    from utils.constants import LIBRARY_DATA_DIR
    scan_file = LIBRARY_DATA_DIR / "libraries.json"
    stored = _load_json(scan_file)

    if not stored:
        return

    # Build path→name lookup from the libraries we just migrated
    path_to_name: dict[str, str] = {}
    for row in conn.execute("SELECT name, path FROM libraries"):
        path_to_name[row["path"]] = row["name"]

    now = time.time()
    count = 0
    for lib_data in stored.values():
        if not isinstance(lib_data, dict):
            continue
        lib_path = lib_data.get("path", "")
        library_name = path_to_name.get(lib_path)
        if not library_name:
            # Library path not in libraries table — skip (no FK target)
            continue

        last_scanned_raw = lib_data.get("last_scanned", "")
        last_scanned = _parse_timestamp(last_scanned_raw) or now

        for book in lib_data.get("books") or []:
            if not isinstance(book, dict):
                continue
            file_path = book.get("file_path")
            if not file_path:
                continue
            conn.execute(
                """
                INSERT OR IGNORE INTO scan_cache
                    (library_name, file_path, asin, title, authors,
                     series, narrator, year, language,
                     file_size, duration_sec, last_scanned)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    library_name,
                    file_path,
                    book.get("asin"),
                    book.get("title"),
                    book.get("authors"),
                    book.get("series"),
                    book.get("narrator"),
                    book.get("year"),
                    book.get("language"),
                    book.get("file_size"),
                    book.get("duration_seconds"),
                    last_scanned,
                ),
            )
            count += 1

    logger.info("Migrated %d scan cache entries", count)


def _parse_timestamp(value: str) -> float:
    """
    Parse an ISO-8601 datetime string to a Unix timestamp float.
    Returns current time if parsing fails.
    """
    if not value:
        return time.time()
    try:
        from datetime import datetime, timezone
        # Handle both naive and aware datetimes
        for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z",
                    "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
            try:
                dt = datetime.strptime(value, fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.timestamp()
            except ValueError:
                continue
    except Exception:
        pass
    return time.time()
