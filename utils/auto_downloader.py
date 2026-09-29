"""
Auto-downloader: polls an Audible account's library and downloads new purchases.
Runs in APScheduler background threads — no Flask request context available here,
so we accept the Flask app instance and use app_context() explicitly.
"""
import asyncio
import logging
import time
from pathlib import Path
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Book fields that can be used in routing rules
ROUTABLE_FIELDS = ('language', 'authors', 'series', 'narrator', 'publisher')


def record_purchases(account_name: str, library: list[dict]) -> None:
    """Keep each account's ownership, including shared ASINs, independently of downloads."""
    from utils.db import transaction

    now = time.time()
    with transaction() as conn:
        for book in library:
            asin = book.get('asin')
            if not asin:
                continue
            conn.execute(
                "INSERT INTO books "
                "(asin, title, authors, series, narrator, publisher, language, "
                "runtime_length_min, status, added_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'wanted', ?, ?) "
                "ON CONFLICT(asin) DO UPDATE SET "
                "authors=COALESCE(books.authors, excluded.authors), "
                "series=COALESCE(books.series, excluded.series), "
                "narrator=COALESCE(books.narrator, excluded.narrator), "
                "publisher=COALESCE(books.publisher, excluded.publisher), "
                "language=COALESCE(books.language, excluded.language), "
                "runtime_length_min=COALESCE(books.runtime_length_min, excluded.runtime_length_min)",
                (asin, book.get('title') or asin, book.get('authors'),
                 book.get('series'), book.get('narrator'), book.get('publisher'),
                 book.get('language'), book.get('length_mins'), now, now),
            )
            conn.execute(
                "INSERT INTO account_books (account_name, asin, first_seen_at, last_seen_at) "
                "VALUES (?, ?, ?, ?) ON CONFLICT(account_name, asin) DO UPDATE SET "
                "last_seen_at=excluded.last_seen_at",
                (account_name, asin, now, now),
            )


def claim_downloads(books: list[dict]) -> list[dict]:
    """Atomically reserve ASINs across concurrent household account jobs."""
    from utils.db import transaction

    claimed = []
    with transaction() as conn:
        for book in books:
            asin = book.get('asin')
            if not asin:
                continue
            changed = conn.execute(
                "UPDATE books SET status='downloading', updated_at=? "
                "WHERE asin=? AND status IN ('wanted', 'missing')",
                (time.time(), asin),
            ).rowcount
            if changed:
                claimed.append(book)
    return claimed


def finish_claims(books: list[dict], results: list) -> None:
    """Release failed claims, and persist paths for successful duplicate matches."""
    from utils.db import transaction

    with transaction() as conn:
        for index, book in enumerate(books):
            result = results[index] if index < len(results) else None
            asin = book['asin']
            if isinstance(result, (str, Path)) and Path(result).is_file():
                conn.execute(
                    "UPDATE books SET status='downloaded', file_path=?, updated_at=? "
                    "WHERE asin=? AND status='downloading'",
                    (str(result), time.time(), asin),
                )
            else:
                conn.execute(
                    "UPDATE books SET status='wanted', updated_at=? "
                    "WHERE asin=? AND status='downloading'",
                    (time.time(), asin),
                )


def mark_missing_downloads(asins: set[str]) -> None:
    """Make vanished local files eligible for a later household download claim."""
    from utils.db import get_db, transaction

    if not asins:
        return
    rows = get_db().execute(
        "SELECT asin, file_path FROM books WHERE status='downloaded' AND file_path IS NOT NULL"
    ).fetchall()
    missing = [(row['asin'], row['file_path']) for row in rows
               if row['asin'] in asins and not Path(row['file_path']).is_file()]
    if not missing:
        return
    with transaction() as conn:
        for asin, file_path in missing:
            conn.execute(
                "UPDATE books SET status='missing', updated_at=? "
                "WHERE asin=? AND status='downloaded' AND file_path=?",
                (time.time(), asin, file_path),
            )


def resolve_library(book: dict, rules: list, default_library_name: str | None) -> str | None:
    """
    Walk the ordered rule list and return the first matching library name.
    Falls back to *default_library_name* (which may be None, meaning skip).

    Matching is case-insensitive substring: rule value must appear somewhere
    in the book's field value.
    """
    for rule in rules:
        field = rule.get('field', '')
        match_value = (rule.get('value') or '').strip().lower()
        if not field or not match_value:
            continue
        book_value = str(book.get(field) or '').lower()
        if match_value in book_value:
            return rule.get('library_name')
    return default_library_name


def run_auto_download(account_name: str, region: str, rules: list, default_library_name: str | None, app, downloads_enabled: bool = True):
    """
    Fetch the Audible library for *account_name*, route each new book to a
    library via the ordered *rules*, and kick off downloads per library.

    Designed to be called from an APScheduler job (background thread).
    """
    from auth import fetch_library
    from downloader import download_books
    from utils.config_manager import get_config_manager

    config_manager = get_config_manager()
    logger.info("Auto-download: starting run for account '%s'", account_name)

    with app.app_context():
        try:
            library = asyncio.run(fetch_library(account_name, region))
        except Exception as exc:
            logger.error("Auto-download: failed to fetch library for '%s': %s", account_name, exc)
            _update_last_run(config_manager, account_name, f"Error fetching library: {exc}")
            return

        if not library:
            logger.warning("Auto-download: empty library returned for '%s'", account_name)
            _update_last_run(config_manager, account_name, "Library empty or unavailable")
            return

        # Store ownership before considering downloads. A shared purchase belongs to
        # every Audible account that returned it, even if only one copy is needed.
        from utils.db import get_db
        known_asins = {row['asin'] for row in get_db().execute(
            "SELECT asin FROM account_books WHERE account_name=?", (account_name,))}
        record_purchases(account_name, library)
        if not downloads_enabled:
            _update_last_run(config_manager, account_name, "Purchases recorded; automatic downloads disabled")
            return

        # A file may have been removed since the last disk scan. Requeue it on
        # this poll instead of treating the stale database status as complete.
        mark_missing_downloads({book['asin'] for book in library if book.get('asin')})

        # Determine which ASINs are already downloaded (authoritative source: books table)
        from app.models import BookStatus
        db = get_db()
        converted_asins = {
            row["asin"]
            for row in db.execute(
                "SELECT asin FROM books WHERE status=?",
                (BookStatus.DOWNLOADED.value,),
            ).fetchall()
        }

        new_books = [b for b in library if b.get('asin') and b['asin'] not in converted_asins]

        # A title this account only just got, but the household already has on disk,
        # is a duplicate we avoided downloading again.
        from utils.events import record_duplicate_avoided
        for book in library:
            asin = book.get('asin')
            if asin and asin not in known_asins and asin in converted_asins:
                record_duplicate_avoided(account_name, asin, book.get('title'))

        if not new_books:
            logger.info("Auto-download: no new books for '%s'", account_name)
            _update_last_run(config_manager, account_name, "No new books")
            return

        # Route each book to its target library
        libraries = config_manager.get_libraries()
        groups: dict[str, list] = {}   # library_name -> [book, ...]
        skipped = 0

        for book in new_books:
            target = resolve_library(book, rules, default_library_name)
            if not target:
                skipped += 1
                logger.debug("Auto-download: no rule matched '%s', skipping", book.get('title'))
                continue
            groups.setdefault(target, []).append(book)

        if not groups:
            msg = f"No new books matched any library rule ({skipped} skipped)"
            logger.info("Auto-download: %s for '%s'", msg, account_name)
            _update_last_run(config_manager, account_name, msg)
            return

        logger.info(
            "Auto-download: %d new book(s) across %d library group(s) for '%s'",
            len(new_books) - skipped, len(groups), account_name
        )

        download_counts: list[str] = []
        for lib_name, books in groups.items():
            lib_config = libraries.get(lib_name, {})
            lib_path = lib_config.get('path', '')
            if not lib_path:
                logger.warning(
                    "Auto-download: library '%s' has no path configured, skipping %d book(s)",
                    lib_name, len(books)
                )
                download_counts.append(f"{lib_name}: missing path")
                continue

            logger.info(
                "Auto-download: downloading %d book(s) to '%s'",
                len(books), lib_name
            )
            try:
                claimed = claim_downloads(books)
                claimed_asins = {b['asin'] for b in claimed}
                for book in books:
                    if book.get('asin') not in claimed_asins:
                        record_duplicate_avoided(account_name, book['asin'], book.get('title'))
                if not claimed:
                    download_counts.append(f"{lib_name}: already claimed")
                    continue
                try:
                    results = asyncio.run(download_books(
                        account_name, region, claimed, library_path=lib_path
                    ))
                except Exception:
                    finish_claims(claimed, [])
                    raise
                finish_claims(claimed, results)
                download_counts.append(f"{lib_name}: {len(claimed)}")
            except Exception as exc:
                logger.error(
                    "Auto-download: download failed for library '%s': %s", lib_name, exc
                )
                download_counts.append(f"{lib_name}: error")

        result = ", ".join(download_counts)
        if skipped:
            result += f" ({skipped} skipped)"
        _update_last_run(config_manager, account_name, result)


def _update_last_run(config_manager, account_name: str, result: str):
    """Persist last_run timestamp and result back to accounts.json."""
    try:
        account = config_manager.get_account(account_name)
        if account is None:
            return
        auto_download = account.get('auto_download', {})
        auto_download['last_run'] = datetime.now(timezone.utc).isoformat()
        auto_download['last_run_result'] = result
        config_manager.update_account(account_name, {'auto_download': auto_download})
    except Exception as exc:
        logger.error("Auto-download: failed to update last_run for '%s': %s", account_name, exc)
