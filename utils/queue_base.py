"""
Base Queue Manager — SQLite-backed abstract base for DownloadQueueManager
and ImportQueueManager.

The in-memory ``_queue`` dict is kept as a write-through cache for the
hot path (SSE progress streaming). Every mutation also writes to the
``download_queue`` / ``download_batches`` tables so state survives restarts.

The legacy ``queue_file`` parameter is accepted but ignored — it is kept
so existing call sites that pass it do not need to be updated.
"""

import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Optional

from utils.db import get_db, transaction


class BaseQueueManager(ABC):
    """
    Abstract base class for queue managers with singleton pattern.
    Backed by the SQLite ``download_queue`` and ``download_batches`` tables.
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, queue_file: Optional[Path] = None):
        """
        Initialise the queue manager (runs once due to singleton pattern).

        Args:
            queue_file: Ignored — kept for call-site compatibility.
        """
        if self._initialized:
            return

        self._initialized = True
        self._queue: Dict = {}

        # Populate in-memory cache from DB
        self._load_queue()

        # Ensure the batch-info sentinel is present in the cache
        if "_batch_info" not in self._queue:
            self._queue["_batch_info"] = {
                "current_batch_id": None,
                "batch_complete": False,
                "batch_start_time": None,
            }

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _load_queue(self) -> None:
        """Populate ``_queue`` from the database."""
        db = get_db()

        # Load batch info
        batch_row = db.execute(
            "SELECT * FROM download_batches ORDER BY started_at DESC LIMIT 1"
        ).fetchone()

        if batch_row:
            self._queue["_batch_info"] = {
                "current_batch_id": batch_row["batch_id"],
                "batch_complete": bool(batch_row["is_complete"]),
                "batch_start_time": batch_row["started_at"],
            }

        # Load all queue entries
        for row in db.execute("SELECT * FROM download_queue"):
            asin = row["asin"]
            self._queue[asin] = self._row_to_item(row)

    def _save_item(self, item_id: str) -> None:
        """Persist a single queue item to the database."""
        item = self._queue.get(item_id)
        if item is None or item_id.startswith("_"):
            return

        now = time.time()
        with transaction() as conn:
            conn.execute(
                """
                INSERT INTO download_queue
                    (asin, title, download_state, batch_id,
                     progress_percent, downloaded_bytes, total_bytes,
                     speed, eta, elapsed, error, error_type, attempts,
                     downloaded_by_account, file_path,
                     added_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(asin) DO UPDATE SET
                    title                 = excluded.title,
                    download_state        = excluded.download_state,
                    batch_id              = excluded.batch_id,
                    progress_percent      = excluded.progress_percent,
                    downloaded_bytes      = excluded.downloaded_bytes,
                    total_bytes           = excluded.total_bytes,
                    speed                 = excluded.speed,
                    eta                   = excluded.eta,
                    elapsed               = excluded.elapsed,
                    error                 = excluded.error,
                    error_type            = excluded.error_type,
                    attempts              = excluded.attempts,
                    downloaded_by_account = excluded.downloaded_by_account,
                    file_path             = excluded.file_path,
                    updated_at            = excluded.updated_at
                """,
                (
                    item_id,
                    item.get("title", ""),
                    item.get("state", "pending"),
                    item.get("batch_id"),
                    item.get("progress_percent"),
                    item.get("downloaded_bytes"),
                    item.get("total_bytes"),
                    item.get("speed"),
                    item.get("eta"),
                    item.get("elapsed"),
                    item.get("error"),
                    item.get("error_type"),
                    item.get("attempts"),
                    item.get("downloaded_by_account"),
                    item.get("file_path"),
                    item.get("added_at", now),
                    now,
                ),
            )

    def _save_batch(self) -> None:
        """Persist current batch info to the database."""
        batch_info = self._queue.get("_batch_info", {})
        batch_id = batch_info.get("current_batch_id")
        if not batch_id:
            return

        with transaction() as conn:
            conn.execute(
                """
                INSERT INTO download_batches (batch_id, is_complete, started_at)
                VALUES (?,?,?)
                ON CONFLICT(batch_id) DO UPDATE SET
                    is_complete  = excluded.is_complete,
                    completed_at = CASE WHEN excluded.is_complete = 1
                                        THEN strftime('%s','now')
                                        ELSE completed_at END
                """,
                (
                    batch_id,
                    1 if batch_info.get("batch_complete") else 0,
                    batch_info.get("batch_start_time", time.time()),
                ),
            )

    # ------------------------------------------------------------------
    # Public API (identical signatures to the old JSON-based version)
    # ------------------------------------------------------------------

    def get_all_items(self) -> Dict:
        """Return all queue items (excluding batch metadata)."""
        return {k: v for k, v in self._queue.items() if not k.startswith("_")}

    def get_item(self, item_id: str) -> Optional[Dict]:
        """Return a specific item, or None if not found."""
        return self._queue.get(item_id)

    def update_item(self, item_id: str, updates: Dict) -> None:
        """Merge ``updates`` into an item and persist."""
        if item_id not in self._queue:
            self._queue[item_id] = {}

        self._queue[item_id].update(updates)
        self._queue[item_id]["last_updated"] = time.time()
        self._save_item(item_id)

    def add_to_queue(self, item_id: str, title: str, initial_state: str, **metadata) -> None:
        """Add a new item to the queue, starting a new batch if needed."""
        batch_info = self._queue.get("_batch_info", {})

        if not batch_info.get("current_batch_id") or batch_info.get("batch_complete", False):
            batch_id = self._generate_batch_id()
            self._queue["_batch_info"] = {
                "current_batch_id": batch_id,
                "batch_complete": False,
                "batch_start_time": time.time(),
            }
            self._save_batch()

        now = time.time()
        self._queue[item_id] = {
            self._get_item_id_key(): item_id,
            "title": title,
            "state": initial_state,
            "added_at": now,
            "last_updated": now,
            "batch_id": self._queue["_batch_info"]["current_batch_id"],
            **metadata,
        }
        self._save_item(item_id)

    def remove_from_queue(self, item_id: str) -> None:
        """Remove an item from the queue."""
        if item_id in self._queue:
            del self._queue[item_id]
            with transaction() as conn:
                conn.execute("DELETE FROM download_queue WHERE asin=?", (item_id,))

    def get_batch_info(self) -> Dict:
        """Return current batch metadata."""
        return self._queue.get("_batch_info", {})

    def mark_batch_complete(self) -> None:
        """Mark the current batch as complete."""
        if "_batch_info" in self._queue:
            self._queue["_batch_info"]["batch_complete"] = True
            self._save_batch()

    def clear_old_items(self, older_than_hours: int = 24) -> int:
        """Remove items from completed batches that are older than the threshold."""
        current_time = time.time()
        cutoff_time = current_time - (older_than_hours * 3600)
        current_batch_id = self._queue.get("_batch_info", {}).get("current_batch_id")

        to_remove = [
            item_id
            for item_id, item in self._queue.items()
            if not item_id.startswith("_")
            and item.get("batch_id") != current_batch_id
            and item.get("last_updated", 0) < cutoff_time
        ]

        for item_id in to_remove:
            del self._queue[item_id]

        if to_remove:
            with transaction() as conn:
                for item_id in to_remove:
                    conn.execute("DELETE FROM download_queue WHERE asin=?", (item_id,))

        return len(to_remove)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_item(row) -> Dict:
        """Convert a sqlite3.Row from download_queue to a dict."""
        return {
            "asin": row["asin"],
            "title": row["title"],
            "state": row["download_state"],
            "batch_id": row["batch_id"],
            "progress_percent": row["progress_percent"],
            "downloaded_bytes": row["downloaded_bytes"],
            "total_bytes": row["total_bytes"],
            "speed": row["speed"],
            "eta": row["eta"],
            "elapsed": row["elapsed"],
            "error": row["error"],
            "error_type": row["error_type"],
            "attempts": row["attempts"],
            "downloaded_by_account": row["downloaded_by_account"],
            "file_path": row["file_path"],
            "added_at": row["added_at"],
            "last_updated": row["updated_at"],
        }

    # ------------------------------------------------------------------
    # Abstract methods (subclasses must implement)
    # ------------------------------------------------------------------

    @abstractmethod
    def get_statistics(self) -> Dict:
        """Return queue statistics."""
        pass

    @abstractmethod
    def _generate_batch_id(self) -> str:
        """Generate a unique batch ID."""
        pass

    @abstractmethod
    def _get_item_id_key(self) -> str:
        """Return the field name used as the item's primary key (e.g. 'asin')."""
        pass

    @abstractmethod
    def _log_warning(self, message: str) -> None:
        """Log a warning message."""
        pass
