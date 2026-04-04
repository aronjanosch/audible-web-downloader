"""
Books management routes.

Provides a simple Sonarr-inspired view of the library:
  - List all tracked books with their status
  - Trigger a library directory scan
  - Mark a book as ignored / un-ignored
  - Re-queue a missing book for download
"""

import asyncio
import logging
from pathlib import Path

from flask import Blueprint, request, jsonify, session

from app.models import BookStatus
from utils.db import get_db, transaction
from utils.config_manager import get_config_manager

books_bp = Blueprint("books", __name__)
logger = logging.getLogger(__name__)
config_manager = get_config_manager()


# ---------------------------------------------------------------------------
# GET /api/books — list all tracked books with optional filtering
# ---------------------------------------------------------------------------

@books_bp.route("/api/books", methods=["GET"])
def list_books():
    """
    Return all tracked books.

    Query parameters:
      status   — filter by BookStatus value (wanted, downloading, downloaded,
                 missing, ignored)
      library  — filter by library name
      q        — case-insensitive substring search on title or authors
    """
    status_filter  = request.args.get("status")
    library_filter = request.args.get("library")
    search         = request.args.get("q", "").strip().lower()

    db = get_db()

    sql  = "SELECT * FROM books WHERE 1=1"
    args = []

    if status_filter:
        sql  += " AND status=?"
        args.append(status_filter)

    if library_filter:
        sql  += " AND library_name=?"
        args.append(library_filter)

    sql += " ORDER BY title"
    rows = db.execute(sql, args).fetchall()

    books = []
    for row in rows:
        book = dict(row)
        if search and search not in (book.get("title") or "").lower() \
                  and search not in (book.get("authors") or "").lower():
            continue
        books.append(book)

    # Status summary
    summary = {s.value: 0 for s in BookStatus}
    for row in db.execute("SELECT status, COUNT(*) as n FROM books GROUP BY status"):
        summary[row["status"]] = row["n"]

    return jsonify({"success": True, "books": books, "summary": summary})


# ---------------------------------------------------------------------------
# POST /api/library/<library_name>/scan — full file-presence scan
# ---------------------------------------------------------------------------

@books_bp.route("/api/library/<library_name>/scan", methods=["POST"])
def scan_library(library_name: str):
    """
    Scan the library directory for M4B files.

    Updates book statuses: files found → downloaded, missing files → missing.
    Returns scan statistics.
    """
    lib = config_manager.get_library(library_name)
    if not lib:
        return jsonify({"error": f"Library '{library_name}' not found"}), 404

    library_path = Path(lib["path"])
    if not library_path.exists():
        return jsonify({"error": f"Library path does not exist: {library_path}"}), 400

    # Use session account or fall back to a generic marker
    account_name = session.get("current_account", "scan")

    from app.services.library_manager import LibraryManager
    manager = LibraryManager(library_path, account_name)

    try:
        stats = manager.scan_library(library_name=library_name)
    except Exception as e:
        logger.error("Library scan failed for %s: %s", library_name, e)
        return jsonify({"error": f"Scan failed: {e}"}), 500

    return jsonify({"success": True, "library": library_name, "stats": stats})


# ---------------------------------------------------------------------------
# POST /api/books/<asin>/ignore
# ---------------------------------------------------------------------------

@books_bp.route("/api/books/<asin>/ignore", methods=["POST"])
def ignore_book(asin: str):
    """Mark a book as ignored (excluded from auto-download)."""
    db = get_db()
    row = db.execute("SELECT asin, title FROM books WHERE asin=?", (asin,)).fetchone()
    if not row:
        return jsonify({"error": "Book not found"}), 404

    with transaction() as conn:
        conn.execute(
            "UPDATE books SET status=?, updated_at=strftime('%s','now') WHERE asin=?",
            (BookStatus.IGNORED.value, asin),
        )

    return jsonify({"success": True, "asin": asin, "status": BookStatus.IGNORED.value})


# ---------------------------------------------------------------------------
# POST /api/books/<asin>/unignore
# ---------------------------------------------------------------------------

@books_bp.route("/api/books/<asin>/unignore", methods=["POST"])
def unignore_book(asin: str):
    """
    Restore an ignored book to 'wanted' (or 'downloaded' if its file still exists).
    """
    db = get_db()
    row = db.execute("SELECT * FROM books WHERE asin=?", (asin,)).fetchone()
    if not row:
        return jsonify({"error": "Book not found"}), 404

    file_path = row["file_path"]
    new_status = (
        BookStatus.DOWNLOADED.value
        if file_path and Path(file_path).exists()
        else BookStatus.WANTED.value
    )

    with transaction() as conn:
        conn.execute(
            "UPDATE books SET status=?, updated_at=strftime('%s','now') WHERE asin=?",
            (new_status, asin),
        )

    return jsonify({"success": True, "asin": asin, "status": new_status})


# ---------------------------------------------------------------------------
# POST /api/books/<asin>/redownload — re-queue a missing book
# ---------------------------------------------------------------------------

@books_bp.route("/api/books/<asin>/redownload", methods=["POST"])
def redownload_book(asin: str):
    """
    Queue a missing (or wanted) book for re-download.

    Requires a library_name in the request body (or falls back to the book's
    stored library_name).  The active account is taken from the session or
    from ``account_name`` in the request body.
    """
    db = get_db()
    row = db.execute("SELECT * FROM books WHERE asin=?", (asin,)).fetchone()
    if not row:
        return jsonify({"error": "Book not found"}), 404

    if row["status"] not in (BookStatus.MISSING.value, BookStatus.WANTED.value):
        return jsonify({
            "error": f"Book status is '{row['status']}' — only missing or wanted books can be re-downloaded"
        }), 409

    body = request.get_json() or {}
    account_name = body.get("account_name") or session.get("current_account")
    library_name = body.get("library_name") or row["library_name"]

    if not account_name:
        return jsonify({"error": "No account selected"}), 400
    if not library_name:
        return jsonify({"error": "No library specified"}), 400

    account_data = config_manager.get_account(account_name)
    if not account_data:
        return jsonify({"error": f"Account '{account_name}' not found"}), 404

    lib = config_manager.get_library(library_name)
    if not lib:
        return jsonify({"error": f"Library '{library_name}' not found"}), 404

    region = account_data.get("region", "us")
    library_path = lib["path"]

    # Fetch the full Audible book record (needed by downloader)
    try:
        from auth import fetch_library
        library = asyncio.run(fetch_library(account_name, region))
        book_record = next((b for b in library if b["asin"] == asin), None)
    except Exception as e:
        logger.error("Could not fetch library for re-download: %s", e)
        return jsonify({"error": f"Failed to fetch library: {e}"}), 500

    if not book_record:
        return jsonify({"error": f"ASIN {asin} not found in Audible library"}), 404

    # Update book status to downloading
    with transaction() as conn:
        conn.execute(
            "UPDATE books SET status=?, updated_at=strftime('%s','now') WHERE asin=?",
            (BookStatus.DOWNLOADING.value, asin),
        )

    # Queue the download
    try:
        from downloader import download_books, count_successful_batch_downloads

        results = asyncio.run(
            download_books(
                account_name,
                region,
                [book_record],
                cleanup_aax=True,
                library_path=library_path,
            )
        )
    except Exception as e:
        # Revert status on failure
        with transaction() as conn:
            conn.execute(
                "UPDATE books SET status=?, updated_at=strftime('%s','now') WHERE asin=?",
                (BookStatus.MISSING.value, asin),
            )
        logger.error("Re-download failed for %s: %s", asin, e)
        return jsonify({"error": f"Re-download failed: {e}"}), 500

    if count_successful_batch_downloads(results) < 1:
        with transaction() as conn:
            conn.execute(
                "UPDATE books SET status=?, updated_at=strftime('%s','now') WHERE asin=?",
                (BookStatus.MISSING.value, asin),
            )
        r0 = results[0] if results else None
        if isinstance(r0, BaseException):
            err = str(r0)
            err_type = type(r0).__name__
        else:
            err = "Download failed"
            err_type = "DownloadFailed"
        logger.error("Re-download failed for %s: %s (%s)", asin, err, err_type)
        return jsonify({"error": f"Re-download failed: {err}", "error_type": err_type}), 500

    path = results[0] if results and not isinstance(results[0], BaseException) else None
    return jsonify(
        {
            "success": True,
            "asin": asin,
            "title": row["title"],
            "message": "Re-download completed",
            "path": path,
        }
    )
