"""
LibraryManager — tracks audiobook library state in the SQLite ``books`` table.

Responsibilities:
- Adding/removing books from the library
- Querying book status by ASIN
- Fuzzy duplicate detection within a library
- Library scan: walk M4B files on disk, update statuses, mark missing files
"""

import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple

from app.models import BookStatus, DownloadState
from utils.db import get_db, transaction
from utils.fuzzy_matching import normalize_for_matching, calculate_similarity
from .metadata_enricher import MetadataEnricher


class LibraryManager:
    """
    Manages the audiobook library state backed by the SQLite ``books`` table.
    """

    def __init__(self, library_path: Path, account_name: str):
        """
        Args:
            library_path: Path to the library directory on disk.
            account_name: Account name used when recording new downloads.
        """
        self.library_path = Path(library_path)
        self.account_name = account_name

        # Provide a compatible in-memory view for legacy callers that access
        # ``library_manager.library_state`` directly (e.g. downloader.py).
        # Values are loaded lazily on first access.
        self._state_cache: Optional[Dict] = None

    # ------------------------------------------------------------------
    # Compatibility shim: library_state property
    # ------------------------------------------------------------------

    @property
    def library_state(self) -> Dict:
        """
        Lazy dict view over the books table for backward compatibility.
        Shape: {asin: {asin, title, file_path, state, timestamp, downloaded_by_account}}
        """
        if self._state_cache is None:
            self._state_cache = self._build_state_cache()
        return self._state_cache

    def _build_state_cache(self) -> Dict:
        db = get_db()
        result: Dict = {}
        for row in db.execute("SELECT * FROM books"):
            asin = row["asin"]
            result[asin] = {
                "asin": asin,
                "title": row["title"],
                "file_path": row["file_path"],
                "state": DownloadState.CONVERTED.value
                if row["status"] == BookStatus.DOWNLOADED.value
                else row["status"],
                "timestamp": row["added_at"],
                "downloaded_by_account": row["downloaded_by_account"],
            }
        return result

    def _invalidate_cache(self) -> None:
        self._state_cache = None

    # ------------------------------------------------------------------
    # Core CRUD
    # ------------------------------------------------------------------

    def get_library_entry(self, asin: str) -> Dict:
        """
        Return the library entry for an ASIN, or an empty dict if not found.
        """
        db = get_db()
        row = db.execute("SELECT * FROM books WHERE asin=?", (asin,)).fetchone()
        if row is None:
            return {}
        return {
            "asin": row["asin"],
            "title": row["title"],
            "file_path": row["file_path"],
            "state": DownloadState.CONVERTED.value
            if row["status"] == BookStatus.DOWNLOADED.value
            else row["status"],
            "timestamp": row["added_at"],
            "downloaded_by_account": row["downloaded_by_account"],
        }

    def add_to_library(self, asin: str, title: str, file_path: str, **metadata) -> None:
        """
        Add or update a book in the library after a successful download.

        Args:
            asin: Amazon Standard Identification Number.
            title: Book title.
            file_path: Absolute path to the finished M4B file.
            **metadata: Optional extra fields (library_name, authors, etc.).
        """
        now = time.time()
        library_name = metadata.get("library_name")
        with transaction() as conn:
            conn.execute(
                """
                INSERT INTO books
                    (asin, title, status, file_path, file_size_bytes,
                     last_seen_on_disk, library_name, downloaded_by_account,
                     added_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(asin) DO UPDATE SET
                    title                 = excluded.title,
                    status                = excluded.status,
                    file_path             = excluded.file_path,
                    file_size_bytes       = excluded.file_size_bytes,
                    last_seen_on_disk     = excluded.last_seen_on_disk,
                    library_name          = excluded.library_name,
                    downloaded_by_account = excluded.downloaded_by_account,
                    updated_at            = excluded.updated_at
                """,
                (
                    asin,
                    title,
                    BookStatus.DOWNLOADED.value,
                    file_path,
                    _file_size(file_path),
                    now,
                    library_name,
                    self.account_name,
                    now,
                    now,
                ),
            )
        self._invalidate_cache()

    def remove_from_library(self, asin: str) -> None:
        """Remove a book from the library."""
        with transaction() as conn:
            conn.execute("DELETE FROM books WHERE asin=?", (asin,))
        self._invalidate_cache()

    def set_status(self, asin: str, status: BookStatus) -> None:
        """Update only the status field for a book."""
        with transaction() as conn:
            conn.execute(
                "UPDATE books SET status=?, updated_at=? WHERE asin=?",
                (status.value, time.time(), asin),
            )
        self._invalidate_cache()

    # ------------------------------------------------------------------
    # Duplicate detection
    # ------------------------------------------------------------------

    def check_fuzzy_duplicate(
        self,
        book_title: str,
        book_authors: str,
        target_library_path: str,
        threshold: float = 0.85,
    ) -> Optional[Tuple[str, str, float]]:
        """
        Check if a book with a similar title already exists in the same library.

        Only compares books within the same library path to allow different
        language versions to coexist in separate libraries.

        Returns:
            (asin, file_path, similarity_score) if a match is found, else None.
        """
        normalized_title = normalize_for_matching(book_title)
        target_lib = str(Path(target_library_path).resolve())

        db = get_db()
        for row in db.execute(
            "SELECT asin, title, file_path FROM books WHERE status=? AND file_path IS NOT NULL",
            (BookStatus.DOWNLOADED.value,),
        ):
            stored_path = row["file_path"]
            if not stored_path or not Path(stored_path).exists():
                continue

            # Only compare books in the same library
            try:
                stored_lib = str(Path(stored_path).resolve().parent)
                if not stored_lib.startswith(target_lib):
                    continue
            except Exception:
                continue

            title_similarity = calculate_similarity(
                normalized_title, normalize_for_matching(row["title"])
            )
            if title_similarity >= threshold:
                return (row["asin"], stored_path, title_similarity)

        return None

    # ------------------------------------------------------------------
    # Library scan — the Sonarr-inspired feature
    # ------------------------------------------------------------------

    def sync_library(self) -> Dict:
        """
        Walk the library directory, update book statuses, and mark missing files.

        For each M4B found on disk:
          - If the ASIN matches an existing book → mark as DOWNLOADED, refresh path.
          - If no matching book exists → insert as a new DOWNLOADED entry.

        After the walk, any book that was previously DOWNLOADED but whose file
        was not seen in this scan is marked as MISSING.

        Returns:
            Stats dict: {files_scanned, asins_found, entries_added,
                         entries_updated, missing_marked, errors}
        """
        return self.scan_library()

    def scan_library(self, library_name: Optional[str] = None) -> Dict:
        """
        Full file-presence scan of the library directory.

        Args:
            library_name: Optional library name to record on new book entries.
                          Uses ``self.account_name`` as the source when absent.

        Returns:
            Stats dict: {files_scanned, asins_found, entries_added,
                         entries_updated, missing_marked, errors}
        """
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{timestamp}] Scanning library: {self.library_path} ...")

        stats = {
            "files_scanned": 0,
            "asins_found": 0,
            "entries_added": 0,
            "entries_updated": 0,
            "missing_marked": 0,
            "errors": 0,
        }

        seen_paths: set[str] = set()
        now = time.time()

        for m4b_file in self.library_path.rglob("*.m4b"):
            stats["files_scanned"] += 1
            file_path_str = str(m4b_file)
            seen_paths.add(file_path_str)

            try:
                asin = MetadataEnricher.extract_asin_from_m4b(m4b_file)

                if asin:
                    stats["asins_found"] += 1
                    from mutagen.mp4 import MP4
                    audiobook = MP4(str(m4b_file))
                    title = audiobook.get("©nam", [None])[0] or m4b_file.stem

                    db = get_db()
                    existing = db.execute(
                        "SELECT asin FROM books WHERE asin=?", (asin,)
                    ).fetchone()

                    if existing:
                        with transaction() as conn:
                            conn.execute(
                                """
                                UPDATE books
                                SET status=?, file_path=?, last_seen_on_disk=?, updated_at=?
                                WHERE asin=?
                                """,
                                (BookStatus.DOWNLOADED.value, file_path_str, now, now, asin),
                            )
                        stats["entries_updated"] += 1
                        print(f"[{timestamp}]   Updated: {title} ({asin})")
                    else:
                        with transaction() as conn:
                            conn.execute(
                                """
                                INSERT OR IGNORE INTO books
                                    (asin, title, status, file_path, file_size_bytes,
                                     last_seen_on_disk, library_name, downloaded_by_account,
                                     added_at, updated_at)
                                VALUES (?,?,?,?,?,?,?,?,?,?)
                                """,
                                (
                                    asin,
                                    title,
                                    BookStatus.DOWNLOADED.value,
                                    file_path_str,
                                    _file_size(file_path_str),
                                    now,
                                    library_name,
                                    "scanned_from_library",
                                    now,
                                    now,
                                ),
                            )
                        stats["entries_added"] += 1
                        print(f"[{timestamp}]   Added: {title} ({asin})")

                # Also upsert into scan_cache
                if library_name:
                    self._upsert_scan_cache(m4b_file, library_name, asin, now)

            except Exception as e:
                stats["errors"] += 1
                print(f"[{timestamp}]   Error processing {m4b_file.name}: {e}")

        # Mark any previously-downloaded books whose files are now gone as MISSING
        db = get_db()
        downloaded_rows = db.execute(
            "SELECT asin, file_path FROM books WHERE status=? AND file_path IS NOT NULL",
            (BookStatus.DOWNLOADED.value,),
        ).fetchall()

        for row in downloaded_rows:
            fp = row["file_path"]
            if fp and fp not in seen_paths and not Path(fp).exists():
                with transaction() as conn:
                    conn.execute(
                        "UPDATE books SET status=?, updated_at=? WHERE asin=?",
                        (BookStatus.MISSING.value, now, row["asin"]),
                    )
                stats["missing_marked"] += 1
                print(f"[{timestamp}]   Missing: {row['asin']} ({fp})")

        self._invalidate_cache()

        print(
            f"[{timestamp}] Scan complete — "
            f"scanned={stats['files_scanned']}, "
            f"added={stats['entries_added']}, "
            f"updated={stats['entries_updated']}, "
            f"missing={stats['missing_marked']}, "
            f"errors={stats['errors']}"
        )
        return stats

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _upsert_scan_cache(
        self, m4b_file: Path, library_name: str, asin: Optional[str], now: float
    ) -> None:
        """Insert or replace a scan_cache row for the given file."""
        try:
            from mutagen.mp4 import MP4
            audio = MP4(str(m4b_file))
            title = (audio.get("©nam") or [None])[0]
            authors = (audio.get("©ART") or audio.get("aART") or [None])[0]
            year = (audio.get("©day") or [None])[0]
            language = None
            duration_sec = audio.info.length if audio.info else None
            file_size = m4b_file.stat().st_size
        except Exception:
            title = m4b_file.stem
            authors = year = language = duration_sec = None
            file_size = None
            try:
                file_size = m4b_file.stat().st_size
            except Exception:
                pass

        with transaction() as conn:
            conn.execute(
                """
                INSERT INTO scan_cache
                    (library_name, file_path, asin, title, authors,
                     year, language, file_size, duration_sec, last_scanned)
                VALUES (?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(file_path) DO UPDATE SET
                    asin         = excluded.asin,
                    title        = excluded.title,
                    authors      = excluded.authors,
                    year         = excluded.year,
                    language     = excluded.language,
                    file_size    = excluded.file_size,
                    duration_sec = excluded.duration_sec,
                    last_scanned = excluded.last_scanned
                """,
                (
                    library_name,
                    str(m4b_file),
                    asin,
                    title,
                    authors,
                    year,
                    language,
                    file_size,
                    duration_sec,
                    now,
                ),
            )


def _file_size(file_path: Optional[str]) -> Optional[int]:
    """Return file size in bytes, or None if unavailable."""
    if not file_path:
        return None
    try:
        return Path(file_path).stat().st_size
    except Exception:
        return None
