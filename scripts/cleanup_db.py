"""
One-time cleanup script: drop the ephemeral download_queue and
download_batches tables from audible.db and bump the schema version to 3.

The download queue is now purely in-memory; these tables are no longer
used.  Running this script while the app is stopped prevents stale
"downloading" or "decrypting" ghost entries from ever re-appearing.

Usage (from project root, with app stopped):
    uv run python scripts/cleanup_db.py [path/to/audible.db]

The default DB path is config/audible.db relative to the working directory.
"""

import sqlite3
import sys
from pathlib import Path

db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("config/audible.db")

if not db_path.exists():
    print(f"Database not found at {db_path} — nothing to do.")
    sys.exit(0)

print(f"Cleaning up {db_path} ...")

db = sqlite3.connect(str(db_path))
try:
    current_version = db.execute("PRAGMA user_version").fetchone()[0]
    print(f"  Current schema version: {current_version}")

    rows_dq = db.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='download_queue'"
    ).fetchone()[0]
    rows_db = db.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='download_batches'"
    ).fetchone()[0]

    if rows_dq:
        count = db.execute("SELECT COUNT(*) FROM download_queue").fetchone()[0]
        db.execute("DROP TABLE download_queue")
        print(f"  Dropped download_queue ({count} rows removed)")
    else:
        print("  download_queue table not present — skipping")

    if rows_db:
        count = db.execute("SELECT COUNT(*) FROM download_batches").fetchone()[0]
        db.execute("DROP TABLE download_batches")
        print(f"  Dropped download_batches ({count} rows removed)")
    else:
        print("  download_batches table not present — skipping")

    db.execute("PRAGMA user_version = 3")
    db.commit()
    print("  Schema version set to 3")
    print("Done.")
finally:
    db.close()
