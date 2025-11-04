"""
Persistent storage for local library data using JSON files.
Handles multiple library configurations and comparison results.
"""

import json
import os
import hashlib
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class LibraryStorage:
    """Manages persistent storage of local library data."""

    def __init__(self, storage_dir: str = "library_data"):
        """Initialize storage with directory for library files."""
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(exist_ok=True)

        # Main files
        self.libraries_file = self.storage_dir / "libraries.json"
        self.comparisons_file = self.storage_dir / "comparisons.json"
        self.config_file = self.storage_dir / "config.json"

    def _generate_library_id(self, library_path: str) -> str:
        """Generate unique ID for library path."""
        # Use hash of path for consistent ID
        return hashlib.md5(library_path.encode()).hexdigest()[:8]

    def save_library(self, library_path: str, books: List[Dict], scan_stats: Optional[Dict] = None) -> str:
        """
        Save local library data to persistent storage.

        Args:
            library_path: Path to the library directory
            books: List of book dictionaries
            scan_stats: Optional scanning statistics

        Returns:
            Library ID for future reference
        """
        library_id = self._generate_library_id(library_path)

        # Load existing libraries
        libraries = self._load_libraries()

        # Create library entry
        library_entry = {
            'id': library_id,
            'path': library_path,
            'books': books,
            'book_count': len(books),
            'last_scanned': datetime.now().isoformat(),
            'stats': scan_stats or {},
            'created': libraries.get(library_id, {}).get('created', datetime.now().isoformat())
        }

        # Calculate additional stats
        library_entry['stats'].update({
            'total_books': len(books),
            'languages': self._calculate_language_stats(books),
            'authors': self._calculate_author_stats(books),
            'series': self._calculate_series_stats(books),
            'total_size_gb': sum(book.get('file_size', 0) for book in books) / (1024**3),
            'avg_duration_hours': sum(book.get('duration_seconds', 0) for book in books) / len(books) / 3600 if books else 0
        })

        # Update libraries
        libraries[library_id] = library_entry

        # Save to file
        self._save_libraries(libraries)

        logger.info(f"Saved library {library_id} with {len(books)} books to {self.libraries_file}")
        return library_id

    def load_library(self, library_id: str) -> Optional[Dict]:
        """Load library data by ID."""
        libraries = self._load_libraries()
        return libraries.get(library_id)

    def load_library_by_path(self, library_path: str) -> Optional[Dict]:
        """Load library data by path."""
        library_id = self._generate_library_id(library_path)
        return self.load_library(library_id)

    def list_libraries(self) -> Dict[str, Dict]:
        """List all stored libraries."""
        return self._load_libraries()

    def delete_library(self, library_id: str) -> bool:
        """Delete a library from storage."""
        libraries = self._load_libraries()

        if library_id in libraries:
            del libraries[library_id]
            self._save_libraries(libraries)

            # Also clean up comparisons for this library
            self._cleanup_comparisons(library_id)

            logger.info(f"Deleted library {library_id}")
            return True

        return False

    def save_comparison(self, library_id: str, audible_account: str, comparison_data: Dict) -> str:
        """
        Save library comparison results.

        Args:
            library_id: ID of local library
            audible_account: Name of Audible account
            comparison_data: Comparison results

        Returns:
            Comparison ID
        """
        comparison_id = f"{library_id}_{audible_account}"

        # Load existing comparisons
        comparisons = self._load_comparisons()

        # Create comparison entry
        comparison_entry = {
            'id': comparison_id,
            'library_id': library_id,
            'audible_account': audible_account,
            'comparison_data': comparison_data,
            'created': datetime.now().isoformat(),
            'stats': {
                'total_audible': comparison_data.get('total_audible', 0),
                'total_local': comparison_data.get('total_local', 0),
                'missing_count': comparison_data.get('missing_count', 0),
                'available_count': comparison_data.get('available_count', 0),
                'coverage_percentage': (comparison_data.get('available_count', 0) /
                                      comparison_data.get('total_audible', 1)) * 100
            }
        }

        comparisons[comparison_id] = comparison_entry
        self._save_comparisons(comparisons)

        logger.info(f"Saved comparison {comparison_id}")
        return comparison_id

    def load_comparison(self, library_id: str, audible_account: str) -> Optional[Dict]:
        """Load comparison results."""
        comparison_id = f"{library_id}_{audible_account}"
        comparisons = self._load_comparisons()
        return comparisons.get(comparison_id)

    def list_comparisons(self) -> Dict[str, Dict]:
        """List all comparisons."""
        return self._load_comparisons()

    def save_config(self, config: Dict):
        """Save application configuration."""
        try:
            with open(self.config_file, 'w') as f:
                json.dump(config, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save config: {e}")

    def load_config(self) -> Dict:
        """Load application configuration."""
        if not self.config_file.exists():
            return {}

        try:
            with open(self.config_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
            return {}

    def get_library_summary(self) -> Dict:
        """Get summary of all libraries and comparisons."""
        libraries = self._load_libraries()
        comparisons = self._load_comparisons()

        return {
            'total_libraries': len(libraries),
            'total_books': sum(lib.get('book_count', 0) for lib in libraries.values()),
            'total_comparisons': len(comparisons),
            'libraries': {
                lib_id: {
                    'path': lib.get('path', ''),
                    'book_count': lib.get('book_count', 0),
                    'last_scanned': lib.get('last_scanned', ''),
                    'size_gb': round(lib.get('stats', {}).get('total_size_gb', 0), 2)
                }
                for lib_id, lib in libraries.items()
            }
        }

    def _load_libraries(self) -> Dict:
        """Load libraries from JSON file."""
        if not self.libraries_file.exists():
            return {}

        try:
            with open(self.libraries_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load libraries: {e}")
            return {}

    def _save_libraries(self, libraries: Dict):
        """Save libraries to JSON file."""
        try:
            with open(self.libraries_file, 'w') as f:
                json.dump(libraries, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save libraries: {e}")
            raise

    def _load_comparisons(self) -> Dict:
        """Load comparisons from JSON file."""
        if not self.comparisons_file.exists():
            return {}

        try:
            with open(self.comparisons_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load comparisons: {e}")
            return {}

    def _save_comparisons(self, comparisons: Dict):
        """Save comparisons to JSON file."""
        try:
            with open(self.comparisons_file, 'w') as f:
                json.dump(comparisons, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save comparisons: {e}")
            raise

    def _cleanup_comparisons(self, library_id: str):
        """Clean up comparisons for a deleted library."""
        comparisons = self._load_comparisons()
        to_delete = [comp_id for comp_id, comp in comparisons.items()
                    if comp.get('library_id') == library_id]

        for comp_id in to_delete:
            del comparisons[comp_id]

        if to_delete:
            self._save_comparisons(comparisons)
            logger.info(f"Cleaned up {len(to_delete)} comparisons for library {library_id}")

    def _calculate_language_stats(self, books: List[Dict]) -> Dict:
        """Calculate language statistics."""
        languages = {}
        for book in books:
            lang = book.get('language', 'unknown')
            languages[lang] = languages.get(lang, 0) + 1
        return languages

    def _calculate_author_stats(self, books: List[Dict]) -> Dict:
        """Calculate author statistics."""
        authors = {}
        for book in books:
            author = book.get('authors', 'Unknown')
            authors[author] = authors.get(author, 0) + 1
        return dict(sorted(authors.items(), key=lambda x: x[1], reverse=True)[:20])  # Top 20

    def _calculate_series_stats(self, books: List[Dict]) -> Dict:
        """Calculate series statistics."""
        series = {}
        for book in books:
            if book.get('series'):
                series_name = book['series']
                series[series_name] = series.get(series_name, 0) + 1
        return dict(sorted(series.items(), key=lambda x: x[1], reverse=True)[:20])  # Top 20
