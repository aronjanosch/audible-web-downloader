"""
LibraryManager service for tracking audiobook library state.

This service is responsible for:
- Loading and saving library state from/to library.json
- Adding books to the library
- Syncing library from filesystem (scanning for existing M4B files)
- Fuzzy duplicate detection
"""

import json
import time
from pathlib import Path
from typing import Optional, Dict, Tuple
from datetime import datetime
from app.models import DownloadState
from utils.fuzzy_matching import normalize_for_matching, calculate_similarity
from .metadata_enricher import MetadataEnricher
from utils.constants import CONFIG_DIR


class LibraryManager:
    """
    Manages the audiobook library state and persistence.
    """

    def __init__(self, library_path: Path, account_name: str):
        """
        Initialize LibraryManager.

        Args:
            library_path: Path to the library directory
            account_name: Account name for tracking downloads
        """
        self.library_path = Path(library_path)
        self.account_name = account_name
        self.library_file = CONFIG_DIR / "library.json"
        self.library_state = self._load_library_state()

    def _load_library_state(self) -> Dict:
        """
        Load the library state from library.json

        Returns:
            Dictionary of library state (ASIN -> book info)
        """
        if self.library_file.exists():
            try:
                return json.load(self.library_file.open('r'))
            except (json.JSONDecodeError, IOError):
                return {}
        return {}

    def _save_library_state(self):
        """Save the library state to library.json"""
        try:
            self.library_file.parent.mkdir(parents=True, exist_ok=True)
            with self.library_file.open('w') as f:
                json.dump(self.library_state, f, indent=2)
        except IOError as e:
            print(f"⚠️  Failed to save library state: {e}")

    def get_library_entry(self, asin: str) -> Dict:
        """
        Get library entry from persistent library.json

        Args:
            asin: Amazon Standard Identification Number

        Returns:
            Dictionary with book information, or empty dict if not found
        """
        return self.library_state.get(asin, {})

    def add_to_library(self, asin: str, title: str, file_path: str, **metadata):
        """
        Add a book to the library state and persist to disk

        Args:
            asin: Amazon Standard Identification Number
            title: Book title
            file_path: Path to the M4B file
            **metadata: Additional metadata to store
        """
        self.library_state[asin] = {
            'asin': asin,
            'title': title,
            'file_path': file_path,
            'state': DownloadState.CONVERTED.value,
            'timestamp': time.time(),
            'downloaded_by_account': self.account_name,
            **metadata
        }
        self._save_library_state()

    def remove_from_library(self, asin: str):
        """
        Remove a book from library state.

        Args:
            asin: Amazon Standard Identification Number
        """
        if asin in self.library_state:
            self.library_state.pop(asin)
            self._save_library_state()

    def check_fuzzy_duplicate(
        self,
        book_title: str,
        book_authors: str,
        target_library_path: str,
        threshold: float = 0.85
    ) -> Optional[Tuple[str, str, float]]:
        """
        Check if a book with similar title and author already exists in the SAME library.
        Only checks books within the same library path to allow different language versions
        in separate libraries.

        Args:
            book_title: Title of the book to check
            book_authors: Author(s) of the book
            target_library_path: Library path where book will be downloaded
            threshold: Similarity threshold (default 0.85)

        Returns:
            Tuple of (asin, file_path, similarity_score) if match found, None otherwise
        """
        normalized_title = normalize_for_matching(book_title)
        normalized_author = normalize_for_matching(book_authors)

        # Normalize library path for comparison
        target_lib = str(Path(target_library_path).resolve())

        for asin, entry in self.library_state.items():
            # Only check converted books
            if entry.get('state') != DownloadState.CONVERTED.value:
                continue

            # Get stored file path
            stored_path = entry.get('file_path')
            if not stored_path or not Path(stored_path).exists():
                continue

            # IMPORTANT: Only check books in the SAME library
            # This allows different language versions in separate libraries
            try:
                stored_lib = str(Path(stored_path).resolve().parent)
                # Check if stored file is in the same library (or subdirectory)
                if not stored_lib.startswith(target_lib):
                    continue  # Skip - different library
            except Exception:
                continue  # Skip if path resolution fails

            # Compare title and author
            stored_title = normalize_for_matching(entry.get('title', ''))
            # Note: authors might not be in entry, we'd need to extract from file metadata
            # For now, focus on title similarity

            author_similarity = calculate_similarity(normalized_author, normalized_author)  # Will enhance this
            title_similarity = calculate_similarity(normalized_title, stored_title)

            # If title is very similar, flag as potential duplicate
            if title_similarity >= threshold:
                return (asin, stored_path, title_similarity)

        return None

    def sync_library(self) -> Dict:
        """
        Scan library directory and populate library.json with existing M4B files.

        Returns:
            Statistics about the sync operation
        """
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{timestamp}] 🔄 Scanning library for existing audiobooks...")

        stats = {
            'files_scanned': 0,
            'asins_found': 0,
            'entries_added': 0,
            'entries_updated': 0,
            'errors': 0
        }

        # Recursively scan library for M4B files
        for m4b_file in self.library_path.rglob('*.m4b'):
            stats['files_scanned'] += 1

            try:
                # Extract ASIN from metadata
                asin = MetadataEnricher.extract_asin_from_m4b(m4b_file)

                if asin:
                    stats['asins_found'] += 1

                    # Extract title from metadata
                    from mutagen.mp4 import MP4
                    audiobook = MP4(str(m4b_file))
                    title = audiobook.get('©nam', [None])[0] or m4b_file.stem

                    # Check if ASIN already in library state
                    existing_entry = self.library_state.get(asin)

                    if existing_entry:
                        # Update existing entry with current file path
                        existing_entry['file_path'] = str(m4b_file)
                        existing_entry['title'] = title
                        existing_entry['timestamp'] = time.time()
                        stats['entries_updated'] += 1
                        print(f"[{timestamp}]   ✓ Updated: {title} ({asin})")
                    else:
                        # Add new entry
                        self.library_state[asin] = {
                            'state': DownloadState.CONVERTED.value,
                            'asin': asin,
                            'title': title,
                            'file_path': str(m4b_file),
                            'timestamp': time.time(),
                            'downloaded_by_account': 'synced_from_library'
                        }
                        stats['entries_added'] += 1
                        print(f"[{timestamp}]   + Added: {title} ({asin})")

            except Exception as e:
                stats['errors'] += 1
                print(f"[{timestamp}]   ⚠️  Error processing {m4b_file.name}: {e}")

        # Save updated library state to disk
        self._save_library_state()

        print(f"[{timestamp}] ✅ Library sync complete!")
        print(f"[{timestamp}]    Files scanned: {stats['files_scanned']}")
        print(f"[{timestamp}]    ASINs found: {stats['asins_found']}")
        print(f"[{timestamp}]    Entries added: {stats['entries_added']}")
        print(f"[{timestamp}]    Entries updated: {stats['entries_updated']}")
        if stats['errors'] > 0:
            print(f"[{timestamp}]    Errors: {stats['errors']}")

        return stats
