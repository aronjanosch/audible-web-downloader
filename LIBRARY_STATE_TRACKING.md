# Library State Tracking Documentation

This document explains the different library-related persistence layers and how they work together.

> **SQLite (`config/audible.db`)** is the runtime source of truth. Legacy JSON files (`config/library.json`, `config/libraries.json`, `library_data/libraries.json`, etc.) may remain on disk from older versions; they are **imported once** when the database is first created (`utils/db.migrate`) and are **not** updated by the current application. Do not rely on those files for operational state.

## Overview

The application uses **three complementary layers**, each with a distinct purpose. All are backed by SQLite tables (accessed through the same manager classes as before):

1. **Download history / book state** — `books` table (`LibraryManager` in `app/services/library_manager.py`)
2. **Library scan cache** — `scan_cache` table (`LibraryStorage` in `library_storage.py`)
3. **Library configuration** — `libraries` table (`ConfigManager` in `utils/config_manager.py`)

---

## 1. Download history and book state

**Storage**: SQLite table `books` in `config/audible.db`  
**Manager**: `app/services/library_manager.py` (`LibraryManager` class)  
**Purpose**: Track which audiobooks have been downloaded (or are wanted, missing, etc.) and where files live

### Logical shape (per ASIN)

Rows include ASIN, title, metadata fields, `status` (`wanted`, `downloading`, `downloaded`, `missing`, `ignored`), `file_path`, optional `library_name` and `downloaded_by_account`, and timestamps.

### Key features

- **ASIN-keyed**: One row per ASIN in the downloader’s library state
- **Status tracking**: Distinguishes wanted, in-progress, completed, and ignored items
- **Account attribution**: Which Audible account downloaded the book (when applicable)
- **File location**: Maps ASINs to paths under configured libraries

### Use cases

1. Duplicate prevention before starting a download
2. Integration with the download pipeline and queue
3. Library sync / rescan workflows using on-disk M4B metadata

### API access

- Used by: `AudiobookDownloader`, download and library routes
- Methods: `LibraryManager.get_library_entry()`, `LibraryManager.add_to_library()`, etc.
- Route: `/api/library/state` (GET) — returns ASIN-oriented state derived from the DB

---

## 2. Library scan cache

**Storage**: SQLite table `scan_cache` in `config/audible.db` (keyed by `library_name` from the `libraries` table)  
**Manager**: `library_storage.py` (`LibraryStorage` class)  
**Purpose**: Store filesystem scan results (paths, extracted metadata, scan timestamps) for local libraries

### Key features

- **Per-library rows**: Entries reference a registered library name and file path
- **Rich metadata**: Title, author, series, ASIN when present, duration, size, etc.
- **Stable library IDs**: Legacy 8-character IDs are still derived from the library path (hash) for API compatibility

### Use cases

1. Library browsing and statistics in the UI
2. Comparing local files to the Audible catalog
3. Search and filter over scanned files

### API access

- Used by: `LocalLibraryScanner`, comparison features
- Methods: `LibraryStorage.save_library()`, `LibraryStorage.load_library_by_path()`, etc.
- Routes: `/api/library/scan-local` (POST), `/api/library/compare` (POST)

**Note**: `library_data/libraries.json` is no longer written; it may exist only as an old backup.

---

## 3. Library configuration

**Storage**: SQLite table `libraries` in `config/audible.db`  
**Manager**: `utils/config_manager.py` (`ConfigManager` class)  
**Purpose**: User-defined library names and filesystem paths

### Logical shape (per library name)

Each row has `name`, `path`, and `created_at`.

### Key features

- **Name → path**: Resolve which folder receives downloads and scans
- **Multiple libraries**: Several roots can be registered

### Use cases

1. Library selection in the UI
2. Path resolution for downloads and scans

### API access

- Methods: `ConfigManager.get_libraries()`, `ConfigManager.save_libraries()`
- Routes: `/api/libraries` (GET, POST), `/api/libraries/<name>` (DELETE)

---

## System interaction flow

### Download flow

1. User selects books from the Audible library (often via cached data in `library_cache`).
2. The downloader checks the `books` table for existing ASINs / status to avoid duplicates where appropriate.
3. Work is tracked in `download_queue` / `download_batches`.
4. After conversion, state is updated in `books` (and temp files under `downloads/` are cleaned up).

### Library scan flow

1. User triggers a scan (e.g. `/api/library/scan-local`).
2. Paths come from the `libraries` table.
3. Scanner walks the filesystem and persists rows into `scan_cache`.
4. Sync logic may reconcile scan results with `books` as implemented in the app.

### Library comparison flow

1. User requests comparison (e.g. `/api/library/compare`).
2. Audible library data is loaded (from cache or API).
3. Local data is loaded from `scan_cache` (via `LibraryStorage`).
4. Results show gaps between cloud catalog and disk.

---

## File / table summary

| Storage | Purpose | Key | Manager |
|--------|---------|-----|---------|
| `books` | Download / library book state | ASIN | `LibraryManager` |
| `scan_cache` | Local filesystem scan results | Path (+ library name) | `LibraryStorage` |
| `libraries` | Registered library roots | Library name | `ConfigManager` |

---

## Conclusion

The three layers remain **complementary**:

- **Configuration** (`libraries`) defines where libraries live on disk.
- **Book state** (`books`) tracks downloader-oriented status and paths for ASINs.
- **Scan cache** (`scan_cache`) reflects what was found on disk during scans.

Together they support downloads, deduplication, browsing, and comparison. All active data for these features lives in **`config/audible.db`**.
