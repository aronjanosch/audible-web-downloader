"""
Base Queue Manager — pure in-memory abstract base for DownloadQueueManager
and ImportQueueManager.

State lives only in the process.  On restart or crash the queue is empty,
which is exactly what we want: no ghost "downloading" entries from a
previous session bleeding into the UI.

The singleton pattern ensures a single shared dict across all Flask threads
(download worker + SSE stream + API requests).
"""

import threading
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Optional


class BaseQueueManager(ABC):
    """
    Abstract base class for in-memory queue managers with singleton pattern.

    All state is held in ``_queue`` (a plain dict).  No DB reads or writes
    happen here; subclasses that need durable side-effects (e.g. updating
    the ``books`` table status) should do so in their own methods.
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
        # Protects concurrent reads/writes from the download thread and SSE stream.
        self._lock = threading.RLock()

        self._queue["_batch_info"] = {
            "current_batch_id": None,
            "batch_complete": False,
            "batch_start_time": None,
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_all_items(self) -> Dict:
        """Return a snapshot of all queue items (excluding batch metadata)."""
        with self._lock:
            return {k: v.copy() for k, v in self._queue.items() if not k.startswith("_")}

    def get_item(self, item_id: str) -> Optional[Dict]:
        """Return a specific item, or None if not found."""
        with self._lock:
            item = self._queue.get(item_id)
            return item.copy() if item else None

    def update_item(self, item_id: str, updates: Dict) -> None:
        """Merge ``updates`` into an existing item."""
        with self._lock:
            if item_id not in self._queue:
                self._queue[item_id] = {}
            self._queue[item_id].update(updates)
            self._queue[item_id]["last_updated"] = time.time()

    def add_to_queue(self, item_id: str, title: str, initial_state: str, **metadata) -> None:
        """Add a new item to the queue, starting a new batch if needed."""
        with self._lock:
            batch_info = self._queue.get("_batch_info", {})

            if not batch_info.get("current_batch_id") or batch_info.get("batch_complete", False):
                batch_id = self._generate_batch_id()
                self._queue["_batch_info"] = {
                    "current_batch_id": batch_id,
                    "batch_complete": False,
                    "batch_start_time": time.time(),
                }

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

    def remove_from_queue(self, item_id: str) -> None:
        """Remove an item from the queue."""
        with self._lock:
            self._queue.pop(item_id, None)

    def get_batch_info(self) -> Dict:
        """Return a copy of current batch metadata."""
        with self._lock:
            return self._queue.get("_batch_info", {}).copy()

    def mark_batch_complete(self) -> None:
        """Mark the current batch as complete."""
        with self._lock:
            if "_batch_info" in self._queue:
                self._queue["_batch_info"]["batch_complete"] = True

    def clear_old_items(self, older_than_hours: int = 24) -> int:
        """Remove items from completed batches that are older than the threshold."""
        cutoff_time = time.time() - (older_than_hours * 3600)
        with self._lock:
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
        return len(to_remove)

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
