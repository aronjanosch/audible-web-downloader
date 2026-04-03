"""
Auto-downloader: polls an Audible account's library and downloads new purchases.
Runs in APScheduler background threads — no Flask request context available here,
so we accept the Flask app instance and use app_context() explicitly.
"""
import asyncio
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Book fields that can be used in routing rules
ROUTABLE_FIELDS = ('language', 'authors', 'series', 'narrator', 'publisher')


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


def run_auto_download(account_name: str, region: str, rules: list, default_library_name: str | None, app):
    """
    Fetch the Audible library for *account_name*, route each new book to a
    library via the ordered *rules*, and kick off downloads per library.

    Designed to be called from an APScheduler job (background thread).
    """
    from auth import fetch_library
    from downloader import download_books, DownloadQueueManager
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

        # Determine which ASINs are already converted
        queue_manager = DownloadQueueManager()
        converted_asins = {
            asin
            for asin, data in queue_manager.get_all_downloads().items()
            if data.get('state') == 'converted'
        }

        new_books = [b for b in library if b['asin'] not in converted_asins]

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
                asyncio.run(download_books(account_name, region, books, library_path=lib_path))
                download_counts.append(f"{lib_name}: {len(books)}")
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
