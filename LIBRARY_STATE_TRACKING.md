# Library State Tracking Documentation

This document explains the different library state tracking systems in the application and how they work together.

## Overview

The application uses **three separate systems** for tracking library-related data, each serving a distinct purpose:

1. **Download History Tracking** (`config/library.json`)
2. **Library Scan Cache** (`library_data/libraries.json`)
3. **Library Configuration** (`config/libraries.json`)

## 1. Download History Tracking

**File**: `config/library.json`  
**Manager**: `app/services/library_manager.py` (`LibraryManager` class)  
**Purpose**: Track which audiobooks have been downloaded and where they are stored

### Data Structure
```json
{
  "B00ABCD123": {
    "asin": "B00ABCD123",
    "title": "Example Audiobook",
    "file_path": "/path/to/library/Author/Book/book.m4b",
    "state": "converted",
    "timestamp": 1699123456.789,
    "downloaded_by_account": "main_account"
  }
}
```

### Key Features
- **ASIN-indexed**: Each entry is keyed by Amazon Standard Identification Number
- **Download state tracking**: Records the conversion state of each download
- **Account attribution**: Tracks which Audible account downloaded each book
- **File location**: Maps ASINs to actual filesystem paths

### Use Cases
1. **Duplicate Prevention**: Check if a book with a given ASIN has already been downloaded
2. **Download Queue Management**: Track the state of ongoing downloads
3. **Library Sync**: Populate download history by scanning existing M4B files for ASINs
4. **Multi-account Support**: Track which account downloaded each book

### API Access
- Used by: `AudiobookDownloader`, `DownloadQueueManager`
- Methods: `LibraryManager.get_library_entry()`, `LibraryManager.add_to_library()`
- Route: `/api/library/state` (GET) - Returns list of ASINs in library

## 2. Library Scan Cache

**File**: `library_data/libraries.json`  
**Manager**: `library_storage.py` (`LibraryStorage` class)  
**Purpose**: Store detailed scan results from filesystem with rich metadata and statistics

### Data Structure
```json
{
  "abc123ef": {
    "id": "abc123ef",
    "path": "/path/to/library",
    "books": [
      {
        "file_path": "/path/to/library/Author/Book/book.m4b",
        "title": "Example Audiobook",
        "authors": "Author Name",
        "series": "Series Name",
        "series_sequence": "1",
        "language": "en",
        "duration_seconds": 36000,
        "file_size": 536870912,
        "asin": "B00ABCD123"
      }
    ],
    "book_count": 1,
    "last_scanned": "2024-11-04T12:34:56",
    "stats": {
      "total_books": 1,
      "languages": {"en": 1},
      "authors": {"Author Name": 1},
      "series": {"Series Name": 1},
      "total_size_gb": 0.5,
      "avg_duration_hours": 10.0
    }
  }
}
```

### Key Features
- **Library ID-indexed**: Each library scan is keyed by a hash of its path
- **Full metadata**: Stores complete metadata extracted from M4B files
- **Statistics**: Calculates aggregate stats (languages, authors, series, size)
- **Comparison data**: Stores results of library comparisons with Audible
- **Historical tracking**: Keeps last scan timestamp and creation date

### Use Cases
1. **Library Browsing**: Display all books in a local library with rich metadata
2. **Statistics Dashboard**: Show library statistics and analytics
3. **Library Comparison**: Compare local library with Audible library to find missing books
4. **Search & Filter**: Search through local library by title, author, series
5. **Multi-library Support**: Manage and compare multiple separate library locations

### API Access
- Used by: `LocalLibraryScanner`, library comparison features
- Methods: `LibraryStorage.save_library()`, `LibraryStorage.load_library_by_path()`
- Routes: `/api/library/scan-local` (POST), `/api/library/compare` (POST)

## 3. Library Configuration

**File**: `config/libraries.json`  
**Manager**: `utils/config_manager.py` (`ConfigManager` class)  
**Purpose**: Store user-configured library locations and settings

### Data Structure
```json
{
  "My Main Library": {
    "path": "/path/to/library",
    "created_at": 1699123456.789
  },
  "Secondary Library": {
    "path": "/another/path/library",
    "created_at": 1699456789.012
  }
}
```

### Key Features
- **Library name-indexed**: User-friendly names for library locations
- **Path configuration**: Maps library names to filesystem paths
- **Multiple libraries**: Support for managing multiple library locations
- **Simple structure**: Lightweight configuration without heavy metadata

### Use Cases
1. **Library Selection**: Allow users to choose which library to download to
2. **Library Management**: Add, remove, or rename library configurations
3. **Path Resolution**: Convert library names to filesystem paths
4. **UI Display**: Show available libraries in dropdowns and selectors

### API Access
- Used by: All routes that need library path resolution
- Methods: `ConfigManager.get_libraries()`, `ConfigManager.save_libraries()`
- Routes: `/api/libraries` (GET, POST), `/api/libraries/<name>` (DELETE)

## System Interaction Flow

### Download Flow
1. User selects books to download from Audible library
2. System checks `config/library.json` (download history) for duplicate ASINs
3. Downloads are queued and processed
4. After conversion, entry is added to `config/library.json` with ASIN and file path

### Library Scan Flow
1. User requests library scan via `/api/library/scan-local`
2. System reads `config/libraries.json` to get library path
3. `LocalLibraryScanner` scans filesystem and extracts metadata
4. Results are saved to `library_data/libraries.json` with full metadata
5. Optionally, ASINs from M4B files update `config/library.json` for sync

### Library Comparison Flow
1. User requests comparison via `/api/library/compare`
2. System loads Audible library (from authenticated session)
3. System loads local library from `library_data/libraries.json`
4. Comparison algorithm matches books by ASIN, title similarity
5. Results show which books are missing locally

## Recommendations

### Current State
All three systems are **necessary and serve distinct purposes**. They should all remain in place.

### Improvements
1. **Add Cross-References**:
   - `library_data/libraries.json` could reference ASINs from `config/library.json`
   - This would enable better duplicate detection during scans

2. **Consolidate Scan Operations**:
   - When scanning library, update both systems simultaneously
   - Ensure consistency between download history and scan cache

3. **Add Validation**:
   - Validate that paths in `config/libraries.json` actually exist
   - Validate that files referenced in `config/library.json` still exist
   - Add consistency checks between systems

4. **Improve Documentation**:
   - Add inline comments explaining the purpose of each system
   - Add this documentation link to README.md
   - Document the interaction between systems in code comments

5. **Add Cleanup Operations**:
   - Remove entries from `config/library.json` when files are deleted
   - Remove stale scan data from `library_data/libraries.json`
   - Add maintenance endpoints for cleanup

6. **Consider Unified Access Layer**:
   - Create a `LibraryService` class that provides unified access to all three systems
   - This would encapsulate the complexity and provide a single API

## File Summary

| File | Purpose | Key | Data Type | Manager |
|------|---------|-----|-----------|---------|
| `config/library.json` | Download history | ASIN | Simple metadata | `LibraryManager` |
| `library_data/libraries.json` | Scan cache | Library ID | Full metadata + stats | `LibraryStorage` |
| `config/libraries.json` | Configuration | Library name | Path only | `ConfigManager` |

## Conclusion

The three library state tracking systems are **complementary, not redundant**:
- **Configuration** (`config/libraries.json`) defines where libraries are
- **Download History** (`config/library.json`) tracks what was downloaded
- **Scan Cache** (`library_data/libraries.json`) stores what's actually on disk

They work together to provide a complete picture of the user's audiobook library.

