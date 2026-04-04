"""
LibraryStorage — scan-cache persistence backed by the SQLite ``scan_cache`` table.

The public API is identical to the old JSON-based implementation so that
``library_scanner.py`` and ``routes/library.py`` callers require no changes.

The old ``library_data/libraries.json`` and ``library_data/comparisons.json``
files are no longer written; they remain on disk as stale backups from the
one-time migration.
"""

import hashlib
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from utils.db import get_db, transaction

logger = logging.getLogger(__name__)


class LibraryStorage:
    """Persistent storage for local library scan data, backed by SQLite."""

    def __init__(self, storage_dir: str = "library_data"):
        # storage_dir is kept for call-site compatibility but is no longer used
        # for active storage. The directory is still created so legacy code that
        # checks for its existence does not error.
        Path(storage_dir).mkdir(exist_ok=True)
        self.storage_dir = Path(storage_dir)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _generate_library_id(self, library_path: str) -> str:
        """Generate a stable 8-char ID from the library path."""
        return hashlib.md5(library_path.encode()).hexdigest()[:8]

    def _path_to_library_name(self, library_path: str) -> Optional[str]:
        """Look up the library name registered for a given path."""
        db = get_db()
        row = db.execute(
            "SELECT name FROM libraries WHERE path=?", (library_path,)
        ).fetchone()
        return row["name"] if row else None

    def _ensure_library_registered(self, library_path: str) -> Optional[str]:
        """
        Return the library name for ``library_path``, or None if the path has
        never been registered via ConfigManager.
        """
        return self._path_to_library_name(library_path)

    # ------------------------------------------------------------------
    # Save / load library scan results
    # ------------------------------------------------------------------

    def save_library(
        self,
        library_path: str,
        books: List[Dict],
        scan_stats: Optional[Dict] = None,
    ) -> str:
        """
        Persist scan results for ``library_path`` into ``scan_cache``.

        Returns the library ID (stable hash of the path, for backward compat).
        """
        library_name = self._path_to_library_name(library_path)
        now = time.time()

        if library_name:
            # Replace all scan_cache rows for this library
            file_paths = {b["file_path"] for b in books if b.get("file_path")}
            with transaction() as conn:
                # Remove stale entries
                conn.execute(
                    "DELETE FROM scan_cache WHERE library_name=?", (library_name,)
                )
                for book in books:
                    fp = book.get("file_path")
                    if not fp:
                        continue
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO scan_cache
                            (library_name, file_path, asin, title, authors,
                             series, narrator, year, language,
                             file_size, duration_sec, last_scanned)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            library_name,
                            fp,
                            book.get("asin"),
                            book.get("title"),
                            book.get("authors"),
                            book.get("series"),
                            book.get("narrator"),
                            book.get("year"),
                            book.get("language"),
                            book.get("file_size"),
                            book.get("duration_seconds"),
                            now,
                        ),
                    )

        library_id = self._generate_library_id(library_path)
        logger.info(
            "Saved %d scan cache entries for library %s (id=%s)",
            len(books),
            library_path,
            library_id,
        )
        return library_id

    def load_library(self, library_id: str) -> Optional[Dict]:
        """
        Load library data by the legacy ``library_id`` hash.

        Looks up the matching library name via the ``libraries`` table,
        then fetches all scan_cache rows for that library.
        """
        db = get_db()
        # Find library by matching the md5 hash of its path
        for row in db.execute("SELECT name, path, created_at FROM libraries"):
            if self._generate_library_id(row["path"]) == library_id:
                return self._build_library_dict(row["name"], row["path"], row["created_at"])
        return None

    def load_library_by_path(self, library_path: str) -> Optional[Dict]:
        """Load library data by path."""
        db = get_db()
        row = db.execute(
            "SELECT name, path, created_at FROM libraries WHERE path=?",
            (library_path,),
        ).fetchone()
        if not row:
            return None
        return self._build_library_dict(row["name"], row["path"], row["created_at"])

    def list_libraries(self) -> Dict[str, Dict]:
        """Return all libraries as {library_id: library_dict}."""
        db = get_db()
        result: Dict[str, Dict] = {}
        for row in db.execute("SELECT name, path, created_at FROM libraries"):
            lib_id = self._generate_library_id(row["path"])
            result[lib_id] = self._build_library_dict(
                row["name"], row["path"], row["created_at"]
            )
        return result

    def delete_library(self, library_id: str) -> bool:
        """Remove all scan_cache entries for the given library_id."""
        lib = self.load_library(library_id)
        if not lib:
            return False
        library_name = lib.get("name")
        if library_name:
            with transaction() as conn:
                conn.execute(
                    "DELETE FROM scan_cache WHERE library_name=?", (library_name,)
                )
        return True

    # ------------------------------------------------------------------
    # Comparison results — simplified (no longer persisted separately)
    # ------------------------------------------------------------------

    def save_comparison(
        self, library_id: str, audible_account: str, comparison_data: Dict
    ) -> str:
        """
        Comparison results are no longer stored separately — the books table
        is the authoritative source of truth for what is missing.

        This method is kept for backward compatibility and returns a
        synthetic comparison_id without persisting anything.
        """
        return f"{library_id}_{audible_account}"

    def load_comparison(
        self, library_id: str, audible_account: str
    ) -> Optional[Dict]:
        """
        Build a comparison result on the fly from the books table.

        Returns a dict in the old shape so existing callers work unchanged.
        """
        lib = self.load_library(library_id)
        if not lib:
            return None

        db = get_db()
        missing = [
            dict(row)
            for row in db.execute(
                "SELECT asin, title, authors, language FROM books WHERE status=?",
                ("missing",),
            )
        ]
        downloaded = db.execute(
            "SELECT COUNT(*) as n FROM books WHERE status=?", ("downloaded",)
        ).fetchone()["n"]
        total = db.execute("SELECT COUNT(*) as n FROM books").fetchone()["n"]

        comparison_data = {
            "missing_from_local": missing,
            "missing_count": len(missing),
            "available_count": downloaded,
            "total_audible": total,
            "total_local": downloaded,
        }
        return {
            "id": f"{library_id}_{audible_account}",
            "library_id": library_id,
            "audible_account": audible_account,
            "comparison_data": comparison_data,
            "created": datetime.now().isoformat(),
            "stats": {
                "total_audible": total,
                "total_local": downloaded,
                "missing_count": len(missing),
                "available_count": downloaded,
                "coverage_percentage": (downloaded / total * 100) if total else 0,
            },
        }

    def list_comparisons(self) -> Dict[str, Dict]:
        """Return an empty dict — comparisons are now derived on demand."""
        return {}

    def save_config(self, config: Dict) -> None:
        """No-op — kept for backward compatibility."""

    def load_config(self) -> Dict:
        """No-op — kept for backward compatibility."""
        return {}

    def get_library_summary(self) -> Dict:
        """Return a summary of all libraries and their scan_cache stats."""
        db = get_db()
        libraries_info: Dict[str, Dict] = {}

        for row in db.execute("SELECT name, path, created_at FROM libraries"):
            lib_id = self._generate_library_id(row["path"])
            count_row = db.execute(
                "SELECT COUNT(*) as n FROM scan_cache WHERE library_name=?",
                (row["name"],),
            ).fetchone()
            size_row = db.execute(
                "SELECT SUM(file_size) as total FROM scan_cache WHERE library_name=?",
                (row["name"],),
            ).fetchone()
            last_scan_row = db.execute(
                "SELECT MAX(last_scanned) as ts FROM scan_cache WHERE library_name=?",
                (row["name"],),
            ).fetchone()

            libraries_info[lib_id] = {
                "path": row["path"],
                "book_count": count_row["n"] if count_row else 0,
                "last_scanned": (
                    datetime.fromtimestamp(last_scan_row["ts"]).isoformat()
                    if last_scan_row and last_scan_row["ts"]
                    else ""
                ),
                "size_gb": round(
                    (size_row["total"] or 0) / (1024**3), 2
                ),
            }

        total_books = sum(v["book_count"] for v in libraries_info.values())
        return {
            "total_libraries": len(libraries_info),
            "total_books": total_books,
            "total_comparisons": 0,
            "libraries": libraries_info,
        }

    # ------------------------------------------------------------------
    # Private builder
    # ------------------------------------------------------------------

    def _build_library_dict(
        self, library_name: str, library_path: str, created_at: float
    ) -> Dict:
        """Build the old-style library dict from scan_cache rows."""
        db = get_db()
        rows = db.execute(
            "SELECT * FROM scan_cache WHERE library_name=?", (library_name,)
        ).fetchall()

        books = [dict(row) for row in rows]

        # Compute aggregate stats
        last_scan_ts = max((b.get("last_scanned") or 0 for b in books), default=None)
        last_scanned_iso = (
            datetime.fromtimestamp(last_scan_ts).isoformat() if last_scan_ts else ""
        )
        total_size = sum(b.get("file_size") or 0 for b in books)
        total_duration = sum(b.get("duration_sec") or 0 for b in books)

        library_id = self._generate_library_id(library_path)
        return {
            "id": library_id,
            "name": library_name,
            "path": library_path,
            "books": books,
            "book_count": len(books),
            "last_scanned": last_scanned_iso,
            "created": (
                datetime.fromtimestamp(created_at).isoformat()
                if created_at
                else ""
            ),
            "stats": {
                "total_books": len(books),
                "total_size_gb": round(total_size / (1024**3), 2),
                "avg_duration_hours": (
                    (total_duration / len(books) / 3600) if books else 0
                ),
            },
        }
