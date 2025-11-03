import asyncio
import audible
import subprocess
from pathlib import Path
import os
import re
import json
import shutil
from enum import Enum
from mutagen.mp4 import MP4
import httpx
import base64
from Crypto.Cipher import AES
from asyncio import Semaphore
import time
import hashlib
import unicodedata
from typing import Optional, Dict, List, Tuple
from settings import get_naming_pattern
from datetime import datetime

class DownloadState(Enum):
    PENDING = "pending"
    RETRYING = "retrying"
    LICENSE_REQUESTED = "license_requested"
    LICENSE_GRANTED = "license_granted"
    DOWNLOADING = "downloading"
    DOWNLOAD_COMPLETE = "download_complete"
    DECRYPTING = "decrypting"
    CONVERTED = "converted"
    ERROR = "error"

class DownloadQueueManager:
    """
    Singleton manager for download queue and progress tracking.
    Provides persistent state storage shared across all downloader instances.
    """
    _instance = None
    _lock = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        # Only initialize once (singleton pattern)
        if self._initialized:
            return
        
        self._initialized = True
        self._queue_file = Path("config") / "download_queue.json"
        self._queue_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Load existing queue or create empty
        self._load_queue()
        
        # Initialize batch tracking
        if '_batch_info' not in self._queue:
            self._queue['_batch_info'] = {
                'current_batch_id': None,
                'batch_complete': False,
                'batch_start_time': None
            }
    
    def _load_queue(self):
        """Load download queue from disk"""
        if self._queue_file.exists():
            try:
                with open(self._queue_file, 'r') as f:
                    self._queue = json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                print(f"Warning: Could not load download queue: {e}")
                self._queue = {}
        else:
            self._queue = {}
    
    def _save_queue(self):
        """Persist download queue to disk"""
        try:
            with open(self._queue_file, 'w') as f:
                json.dump(self._queue, f, indent=2)
        except IOError as e:
            print(f"Warning: Could not save download queue: {e}")
    
    def get_all_downloads(self) -> Dict:
        """Get all downloads in the queue (excluding batch info)"""
        # Return a copy without the batch metadata
        downloads = {k: v for k, v in self._queue.items() if not k.startswith('_')}
        return downloads
    
    def get_download(self, asin: str) -> Optional[Dict]:
        """Get a specific download by ASIN"""
        return self._queue.get(asin)
    
    def update_download(self, asin: str, updates: Dict):
        """Update download state"""
        if asin not in self._queue:
            self._queue[asin] = {}
        
        # Merge updates into existing entry
        self._queue[asin].update(updates)
        self._queue[asin]['last_updated'] = time.time()
        
        # Persist to disk
        self._save_queue()
    
    def add_to_queue(self, asin: str, title: str, **metadata):
        """Add a new download to the queue"""
        # Check if we need to start a new batch
        batch_info = self._queue.get('_batch_info', {})
        
        # Start a new batch if:
        # 1. No current batch exists, OR
        # 2. Current batch is marked complete
        if not batch_info.get('current_batch_id') or batch_info.get('batch_complete', False):
            # Start a new batch
            batch_id = f"batch_{int(time.time())}"
            self._queue['_batch_info'] = {
                'current_batch_id': batch_id,
                'batch_complete': False,
                'batch_start_time': time.time()
            }
        
        self._queue[asin] = {
            'asin': asin,
            'title': title,
            'state': DownloadState.PENDING.value,
            'added_at': time.time(),
            'last_updated': time.time(),
            'batch_id': self._queue['_batch_info']['current_batch_id'],
            **metadata
        }
        self._save_queue()
    
    def remove_from_queue(self, asin: str):
        """Remove a download from the queue"""
        if asin in self._queue:
            del self._queue[asin]
            self._save_queue()
    
    def get_statistics(self) -> Dict:
        """Get download statistics"""
        batch_info = self._queue.get('_batch_info', {})
        current_batch_id = batch_info.get('current_batch_id')
        
        stats = {
            'active': 0,
            'queued': 0,
            'completed': 0,
            'failed': 0,
            'total_speed': 0,
            'total_downloads': 0,
            'batch_complete': batch_info.get('batch_complete', False),
            'batch_id': current_batch_id
        }
        
        for asin, download in self._queue.items():
            # Skip metadata entries
            if asin.startswith('_'):
                continue
                
            # Only count downloads in current batch
            if download.get('batch_id') != current_batch_id:
                continue
                
            stats['total_downloads'] += 1
            state = download.get('state', '')
            
            if state in ['pending', 'retrying']:
                stats['queued'] += 1
            elif state in ['license_requested', 'license_granted', 'downloading', 'download_complete', 'decrypting']:
                stats['active'] += 1
                # Add up download speeds for active downloads
                if 'speed' in download:
                    stats['total_speed'] += download['speed']
            elif state == 'converted':
                stats['completed'] += 1
            elif state == 'error':
                stats['failed'] += 1
        
        # Check if batch is complete (all downloads finished)
        if stats['total_downloads'] > 0 and stats['active'] == 0 and stats['queued'] == 0:
            if not batch_info.get('batch_complete', False):
                # Mark batch as complete
                self._queue['_batch_info']['batch_complete'] = True
                self._save_queue()
                stats['batch_complete'] = True
        
        return stats
    
    def clear_completed(self, older_than_hours: int = 24):
        """Remove completed downloads older than specified hours"""
        current_time = time.time()
        cutoff_time = current_time - (older_than_hours * 3600)
        
        asins_to_remove = []
        for asin, download in self._queue.items():
            if download.get('state') == 'converted':
                last_updated = download.get('last_updated', 0)
                if last_updated < cutoff_time:
                    asins_to_remove.append(asin)
        
        for asin in asins_to_remove:
            del self._queue[asin]
        
        if asins_to_remove:
            self._save_queue()
        
        return len(asins_to_remove)

class AudiobookDownloader:
    def __init__(self, account_name, region="us", max_concurrent_downloads=3, library_path=None, downloads_dir=None):
        self.account_name = account_name
        self.region = region

        if not library_path:
            raise ValueError("library_path is required. Please configure a library before downloading.")

        # Separate temporary downloads directory from final library path
        self.library_path = Path(library_path)
        self.library_path.mkdir(parents=True, exist_ok=True)

        # Use provided downloads_dir or default to "downloads" in project root
        if downloads_dir:
            self.downloads_dir = Path(downloads_dir)
        else:
            self.downloads_dir = Path("downloads")

        self.downloads_dir.mkdir(parents=True, exist_ok=True)
        self.download_semaphore = Semaphore(max_concurrent_downloads)
        self.decrypt_semaphore = Semaphore(1)

        self.auth = self._load_authenticator()
        self._auth_details = self._load_auth_details() if self.auth else None

        # Library tracking file - persists which books are in the library
        self.library_file = Path("config") / "library.json"
        self.library_state = self._load_library_state()

        # Use shared queue manager for download progress tracking (persisted to disk)
        self.queue_manager = DownloadQueueManager()

        # Track download start times for elapsed time reporting
        self.download_start_times = {}

    @staticmethod
    def _format_bytes(bytes_value: int) -> str:
        """Format bytes to human-readable format."""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if bytes_value < 1024.0:
                return f"{bytes_value:.2f} {unit}"
            bytes_value /= 1024.0
        return f"{bytes_value:.2f} TB"

    @staticmethod
    def _format_elapsed_time(seconds: float) -> str:
        """Format elapsed time to human-readable format."""
        if seconds < 60:
            return f"{seconds:.0f}s"
        elif seconds < 3600:
            minutes = seconds / 60
            return f"{minutes:.1f}m"
        else:
            hours = seconds / 3600
            return f"{hours:.1f}h"

    def _log(self, message: str, asin: str = None):
        """Log message with timestamp and optional book identifier."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        if asin and asin in self.download_start_times:
            elapsed = time.time() - self.download_start_times[asin]
            elapsed_str = self._format_elapsed_time(elapsed)
            print(f"[{timestamp}] [{elapsed_str}] {message}")
        else:
            print(f"[{timestamp}] {message}")

    def _load_authenticator(self) -> Optional[audible.Authenticator]:
        """Loads the authenticator object from file."""
        auth_file = Path("config") / "auth" / self.account_name / "auth.json"
        if auth_file.exists():
            return audible.Authenticator.from_file(auth_file)
        return None

    def _load_auth_details(self) -> Optional[Dict]:
        """Loads the raw auth JSON file for details not exposed by the authenticator."""
        auth_file = Path("config") / "auth" / self.account_name / "auth.json"
        if auth_file.exists():
            return json.loads(auth_file.read_text())
        return None

    def _load_library_state(self) -> Dict:
        """Loads the library state from library.json"""
        if self.library_file.exists():
            try:
                return json.load(self.library_file.open('r'))
            except (json.JSONDecodeError, IOError):
                return {}
        return {}

    def _save_library_state(self):
        """Saves the library state to library.json"""
        try:
            self.library_file.parent.mkdir(parents=True, exist_ok=True)
            with self.library_file.open('w') as f:
                json.dump(self.library_state, f, indent=2)
        except IOError as e:
            self._log(f"⚠️  Failed to save library state: {e}")

    def _decrypt_voucher(self, asin: str, license_response: Dict) -> Optional[Dict]:
        """Decrypts the license response voucher to get key and IV."""
        try:
            if not self._auth_details:
                raise Exception("Authentication details not loaded.")

            device_serial = self._auth_details["device_info"]["device_serial_number"]
            customer_id = self._auth_details["customer_info"]["user_id"]
            device_type = self._auth_details["device_info"]["device_type"]

            voucher_b64 = license_response["content_license"]["license_response"]
            voucher_data = base64.b64decode(voucher_b64)

            buf = (device_type + device_serial + customer_id + asin).encode("ascii")
            digest = hashlib.sha256(buf).digest()
            key = digest[0:16]
            iv = digest[16:]

            cipher = AES.new(key, AES.MODE_CBC, iv)
            plaintext = cipher.decrypt(voucher_data)

            last_brace = plaintext.rindex(b'}')
            plaintext = plaintext[:last_brace + 1]

            return json.loads(plaintext)
        except Exception as e:
            self._log(f"❌ Failed to decrypt voucher: {e}", asin)
            return None


    def get_download_state(self, asin: str) -> Dict:
        """Get download state from shared queue manager"""
        return self.queue_manager.get_download(asin) or {}

    def get_library_entry(self, asin: str) -> Dict:
        """Get library entry from persistent library.json"""
        return self.library_state.get(asin, {})

    def add_to_library(self, asin: str, title: str, file_path: str, **metadata):
        """Add a book to the library state and persist to disk"""
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
    
    def set_download_state(self, asin: str, state: DownloadState, **metadata):
        # Check if this is a new download
        existing = self.queue_manager.get_download(asin)
        
        if not existing:
            # New download - add to queue with batch tracking
            title = metadata.get('title', 'Unknown')
            self.queue_manager.add_to_queue(asin, title, downloaded_by_account=self.account_name)
        
        # Always include ASIN and account info in state
        update_data = {
            'state': state.value,
            'timestamp': time.time(),
            'asin': asin,
            **metadata
        }

        # Add account info if not already present
        if not existing or 'downloaded_by_account' not in existing:
            update_data['downloaded_by_account'] = self.account_name

        self.queue_manager.update_download(asin, update_data)
    
    def update_download_progress(self, asin: str, downloaded_bytes: int, total_bytes: int = None, **metadata):
        """Update download progress without changing state"""
        progress_data = {
            'downloaded_bytes': downloaded_bytes,
            'progress_timestamp': time.time(),
            **metadata
        }

        if total_bytes is not None:
            progress_data['total_bytes'] = total_bytes
            progress_data['progress_percent'] = min(100, (downloaded_bytes / total_bytes) * 100) if total_bytes > 0 else 0

        self.queue_manager.update_download(asin, progress_data)
    
    def _sanitize_filename(self, filename):
        return re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f-\x9f]', '_', filename)[:200]

    def _format_author(self, authors) -> str:
        """
        Format author name(s) from various input formats, excluding translators.
        Translators are identified by:
        1. Explicit markers like "- Übersetzer", "- Translator"
        2. Having no ASIN when other authors have ASINs (likely translator/contributor)
        """
        if isinstance(authors, str):
            return authors if authors else "Unknown Author"
        elif isinstance(authors, list) and authors:
            # Filter out translators by explicit markers first
            translator_markers = [
                '- übersetzer', '- translator', '- traducteur', '- traductor',
                '- traduttore', '- vertaler', '- översättare'
            ]
            
            primary_authors = []
            for author in authors:
                name = author.get('name', '') if isinstance(author, dict) else str(author)
                if not name:
                    continue
                    
                # Check for explicit translator marker
                is_translator = any(marker in name.lower() for marker in translator_markers)
                if not is_translator:
                    primary_authors.append(author)
            
            # If no explicit filtering happened, check for ASIN-based filtering
            # Authors with ASINs are usually primary authors; those without might be translators
            if len(primary_authors) > 1:
                authors_with_asin = [a for a in primary_authors if isinstance(a, dict) and a.get('asin')]
                if authors_with_asin:
                    # If we have authors with ASINs, only use those
                    primary_authors = authors_with_asin
            
            # Extract names for final formatting
            author_names = []
            for author in primary_authors:
                name = author.get('name', '') if isinstance(author, dict) else str(author)
                if name:
                    author_names.append(name)
            
            # Fallback to all author names if filtering removed everyone
            if not author_names:
                author_names = [author.get('name', '') if isinstance(author, dict) else str(author) for author in authors]
                author_names = [name for name in author_names if name]

            if len(author_names) > 3:
                return "Various Authors"
            elif len(author_names) > 2:
                return ", ".join(author_names[:-1]) + " and " + author_names[-1]
            elif len(author_names) == 2:
                return " & ".join(author_names)
            elif len(author_names) == 1:
                return author_names[0]
        return "Unknown Author"

    def _format_narrator(self, narrators) -> str:
        """Format narrator name(s) from various input formats."""
        if isinstance(narrators, str):
            return narrators if narrators else ""
        elif isinstance(narrators, list) and narrators:
            narrator_names = [n.get('name', '') if isinstance(n, dict) else str(n) for n in narrators[:2]]
            narrator_names = [name for name in narrator_names if name]
            if narrator_names:
                return " & ".join(narrator_names)
        return ""

    def _format_series(self, series) -> tuple[Optional[str], Optional[str]]:
        """
        Format series information.
        Returns: (series_name, volume_number)
        """
        if isinstance(series, str) and series:
            return series, None
        elif isinstance(series, list) and series:
            series_name = series[0].get('title', '') if series[0].get('title') else None
            volume = series[0].get('sequence', None)
            return series_name, volume
        return None, None

    def _normalize_for_matching(self, text: str) -> str:
        """Normalize text for fuzzy matching (used for duplicate detection)."""
        if not text:
            return ""

        # Convert to lowercase
        text = text.lower()

        # Remove diacritics
        text = unicodedata.normalize('NFD', text)
        text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')

        # Replace common separators and punctuation with spaces
        text = re.sub(r'[:\-_,.;!?()[\]{}"\']', ' ', text)

        # Remove common volume/part indicators
        replacements = ['band', 'teil', 'buch', 'volume', 'vol', 'part', 'pt']
        for word in replacements:
            text = re.sub(r'\b' + word + r'\b', '', text)

        # Remove extra whitespace
        text = re.sub(r'\s+', ' ', text).strip()

        return text

    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """Calculate word-based similarity between two texts (Jaccard similarity)."""
        if not text1 or not text2:
            return 0.0

        # Simple exact match after normalization
        if text1 == text2:
            return 1.0

        # Word-based similarity
        words1 = set(text1.split())
        words2 = set(text2.split())

        if not words1 or not words2:
            return 0.0

        # Calculate Jaccard similarity
        intersection = len(words1.intersection(words2))
        union = len(words1.union(words2))
        jaccard = intersection / union if union > 0 else 0.0

        # Bonus for substring containment
        substring_bonus = 0.0
        if text1 in text2 or text2 in text1:
            substring_bonus = 0.2

        # Check for number/volume matching
        numbers1 = set(re.findall(r'\d+', text1))
        numbers2 = set(re.findall(r'\d+', text2))

        number_bonus = 0.0
        if numbers1 and numbers2:
            number_match = len(numbers1.intersection(numbers2)) / max(len(numbers1), len(numbers2))
            number_bonus = number_match * 0.3

        final_score = min(1.0, jaccard + substring_bonus + number_bonus)

        return final_score

    def _check_fuzzy_duplicate(self, book_title: str, book_authors: str, target_library_path: str, threshold: float = 0.85) -> Optional[Tuple[str, str, float]]:
        """
        Check if a book with similar title and author already exists in the SAME library.
        Only checks books within the same library path to allow different language versions in separate libraries.

        Args:
            book_title: Title of the book to check
            book_authors: Author(s) of the book
            target_library_path: Library path where book will be downloaded
            threshold: Similarity threshold (default 0.85)

        Returns: (asin, file_path, similarity_score) of matching book, or None
        """
        normalized_title = self._normalize_for_matching(book_title)
        normalized_author = self._normalize_for_matching(book_authors)

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
            stored_title = self._normalize_for_matching(entry.get('title', ''))
            # Note: authors might not be in entry, we'd need to extract from file metadata
            # For now, focus on title similarity

            author_similarity = self._calculate_similarity(normalized_author, normalized_author)  # Will enhance this
            title_similarity = self._calculate_similarity(normalized_title, stored_title)

            # If title is very similar, flag as potential duplicate
            if title_similarity >= threshold:
                return (asin, stored_path, title_similarity)

        return None

    @staticmethod
    def extract_asin_from_m4b(file_path: Path) -> Optional[str]:
        """
        Extract ASIN from M4B file metadata.
        ASIN is stored in ©cmt tag as "ASIN: {asin}"
        """
        try:
            audiobook = MP4(str(file_path))

            # Check ©cmt tag for ASIN
            comment = audiobook.get('©cmt')
            if comment and len(comment) > 0:
                comment_text = comment[0]
                # Look for "ASIN: B..." pattern
                match = re.search(r'ASIN:\s*([A-Z0-9]{10})', comment_text)
                if match:
                    return match.group(1)

        except Exception as e:
            pass

        return None

    def sync_library(self) -> Dict:
        """
        Scan library directory and populate library.json with existing M4B files.
        Returns: Statistics about the sync operation
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
                asin = self.extract_asin_from_m4b(m4b_file)

                if asin:
                    stats['asins_found'] += 1

                    # Extract title from metadata
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

    def _process_conditional_brackets(self, pattern: str, replacements: dict) -> str:
        """
        Process conditional bracket syntax [text {Placeholder}].
        If any placeholder inside brackets is empty, the entire bracketed section is removed.

        Args:
            pattern: Naming pattern with conditional brackets
            replacements: Dictionary of placeholder values

        Returns:
            Pattern with conditional sections resolved
        """
        import re

        # Process brackets from innermost to outermost to handle nested brackets
        max_iterations = 10  # Prevent infinite loops
        iteration = 0

        while '[' in pattern and iteration < max_iterations:
            iteration += 1

            # Find the innermost bracket pair (no nested brackets inside)
            # Pattern: [ followed by anything except [ or ], then ]
            match = re.search(r'\[([^\[\]]*)\]', pattern)

            if not match:
                break

            bracketed_content = match.group(1)
            full_match = match.group(0)

            # Check if any placeholder in the bracketed content is empty
            should_include = True
            for placeholder, value in replacements.items():
                if placeholder in bracketed_content:
                    # If this placeholder is empty/None, exclude the entire bracket
                    if not value or value == "":
                        should_include = False
                        break

            # Replace the bracketed section
            if should_include:
                # Keep the content, remove the brackets
                pattern = pattern.replace(full_match, bracketed_content, 1)
            else:
                # Remove the entire bracketed section
                pattern = pattern.replace(full_match, '', 1)

        return pattern

    def _cleanup_pattern(self, text: str) -> str:
        """
        Clean up the pattern by removing extra spaces, dashes, and empty brackets.

        Args:
            text: Text to clean up

        Returns:
            Cleaned text
        """
        import re

        # Remove empty brackets/parentheses: (), [], {}
        text = re.sub(r'\(\s*\)', '', text)
        text = re.sub(r'\[\s*\]', '', text)
        text = re.sub(r'\{\s*\}', '', text)

        # Clean up multiple spaces
        text = re.sub(r'\s+', ' ', text)

        # Clean up spaces around dashes: " - " with multiple spaces becomes " - "
        text = re.sub(r'\s*-\s*', ' - ', text)

        # Remove leading/trailing dashes with spaces: " - text" or "text - "
        text = re.sub(r'^\s*-\s*', '', text)
        text = re.sub(r'\s*-\s*$', '', text)

        # Clean up multiple consecutive dashes: " - - " becomes " - "
        text = re.sub(r'(\s*-\s*)+', ' - ', text)

        # Final trim
        text = text.strip()

        return text

    def build_path_from_pattern(
        self,
        base_path: str,
        title: str,
        authors=None,
        narrators=None,
        series=None,
        release_date: str = None,
        publisher: str = None,
        language: str = None,
        asin: str = None
    ) -> Path:
        """
        Build a file path based on the current naming pattern from settings.

        Args:
            base_path: Base directory path
            title: Book title
            authors: Author(s) information (string or list of dicts)
            narrators: Narrator(s) information (string or list of dicts)
            series: Series information (string or list of dicts)
            release_date: Release date string (YYYY-MM-DD format)
            publisher: Publisher name
            language: Book language
            asin: Amazon Standard Identification Number

        Returns:
            Path object with the complete file path
        """
        # Get the current naming pattern from settings
        pattern = get_naming_pattern()

        # Format metadata components
        author_str = self._format_author(authors)
        narrator_str = self._format_narrator(narrators)
        series_name, volume = self._format_series(series)

        # Extract year from release date
        year = ""
        if release_date:
            year = release_date.split('-')[0]

        # Create placeholder replacements - all placeholders are now simple/atomic
        replacements = {
            '{Author}': author_str,
            '{Series}': series_name if series_name else "",
            '{Title}': title,  # Just the raw book title
            '{Year}': year,
            '{Narrator}': narrator_str,
            '{Publisher}': publisher if publisher else "",
            '{Language}': language if language else "",
            '{ASIN}': asin if asin else "",
            '{Volume}': str(volume) if volume else ""  # Just the number (e.g., "1", "2")
        }

        # Process conditional brackets first (before placeholder replacement)
        path_str = self._process_conditional_brackets(pattern, replacements)

        # Replace placeholders in pattern
        for placeholder, value in replacements.items():
            path_str = path_str.replace(placeholder, value)

        # Clean up path: remove empty segments and consecutive slashes
        path_parts = []
        for part in path_str.split('/'):
            part = part.strip()
            if part:  # Skip empty segments (happens when optional placeholders are empty)
                # Apply cleanup to remove extra spaces, dashes, and empty brackets
                part = self._cleanup_pattern(part)
                if part:  # Check again after cleanup
                    # Sanitize each path component
                    sanitized = self._sanitize_filename(part)
                    if sanitized and sanitized != ".m4b":  # Don't add segments that are just the extension
                        path_parts.append(sanitized)

        # Build final path directly from pattern (pattern is the source of truth)
        if not path_parts:
            # Fallback to flat structure if pattern results in empty path
            safe_title = self._sanitize_filename(title)
            return Path(base_path) / safe_title / f"{safe_title}.m4b"

        # Join all parts to create the full path as defined by the pattern
        return Path(base_path).joinpath(*path_parts)

    def build_audiobookshelf_path(
        self,
        base_path: str,
        title: str,
        authors: List[Dict] = None,
        narrators: List[Dict] = None,
        series: List[Dict] = None,
        release_date: str = None,
        use_audiobookshelf_structure: bool = False
    ) -> Path:
        """
        Build AudioBookshelf-compatible directory path.

        Returns:
            Path object with structure: base_path/Author/[Series]/Title/
        """
        if not use_audiobookshelf_structure:
            # Legacy flat structure
            return Path(base_path) / self._sanitize_filename(title)

        # 1. Build Author Folder
        # Handle both string format (from library) and list format (from API)
        if isinstance(authors, str):
            # Already a formatted string from library fetch
            author_folder = authors if authors else "Unknown Author"
        elif isinstance(authors, list) and authors:
            # List of dicts from API
            author_names = [author.get('name', '') if isinstance(author, dict) else str(author) for author in authors]
            author_names = [name for name in author_names if name]  # Filter empty strings

            if len(author_names) > 3:
                author_folder = "Various Authors"
            elif len(author_names) > 2:
                author_folder = ", ".join(author_names[:-1]) + " and " + author_names[-1]
            elif len(author_names) == 2:
                author_folder = " & ".join(author_names)
            elif len(author_names) == 1:
                author_folder = author_names[0]
            else:
                author_folder = "Unknown Author"
        else:
            author_folder = "Unknown Author"

        author_folder = self._sanitize_filename(author_folder)

        # 2. Build Series Folder (Optional)
        series_folder = None
        series_sequence = None

        if isinstance(series, str):
            # Series is a string from library fetch
            if series:
                series_folder = self._sanitize_filename(series)
        elif isinstance(series, list) and series:
            # Series is a list from API
            if series[0].get('title'):
                series_folder = self._sanitize_filename(series[0]['title'])
            series_sequence = series[0].get('sequence')

        # 3. Build Title Folder
        title_parts = []

        # Add sequence if in series
        if series_sequence:
            # Format sequence (e.g., "Vol. 1" or "Vol. 1.5")
            title_parts.append(f"Vol. {series_sequence}")

        # Add year
        if release_date:
            year = release_date.split('-')[0]  # Extract YYYY from YYYY-MM-DD
            title_parts.append(year)

        # Add title
        title_parts.append(title)

        # Build title folder with narrator in curly braces
        # Handle both string format (from library) and list format (from API)
        narrator_str = None
        if isinstance(narrators, str):
            # Already a formatted string from library fetch
            narrator_str = narrators if narrators else None
        elif isinstance(narrators, list) and narrators:
            # List of dicts from API
            narrator_names = [n.get('name', '') if isinstance(n, dict) else str(n) for n in narrators[:2]]
            narrator_names = [name for name in narrator_names if name]  # Filter empty strings
            if narrator_names:
                narrator_str = " & ".join(narrator_names)

        if narrator_str:
            title_folder = " - ".join(title_parts) + f" {{{narrator_str}}}"
        else:
            title_folder = " - ".join(title_parts)

        title_folder = self._sanitize_filename(title_folder)

        # 4. Construct Path
        if series_folder:
            return Path(base_path) / author_folder / series_folder / title_folder
        else:
            return Path(base_path) / author_folder / title_folder

    def _get_file_paths(self, book_title: str, asin: str, product: Dict = None) -> Dict[str, Path]:
        """
        Build file paths for temporary downloads and final library location.
        Temp files (AAX, vouchers, metadata) go to downloads_dir.
        Final M4B file goes to library_path following naming pattern.
        """
        # 1. Create temporary download directory (simple sanitized title)
        safe_title = self._sanitize_filename(book_title)
        temp_dir = self.downloads_dir / safe_title
        temp_dir.mkdir(parents=True, exist_ok=True)

        # 2. Build final library path using naming pattern
        if product:
            try:
                # Use the new pattern-based path builder for final library location
                series_info = product.get('series_data') or product.get('series')

                final_m4b_path = self.build_path_from_pattern(
                    base_path=str(self.library_path),
                    title=book_title,
                    authors=product.get('authors', []),
                    narrators=product.get('narrator') or product.get('narrators', []),
                    series=series_info,
                    release_date=product.get('release_date'),
                    publisher=product.get('publisher'),
                    language=product.get('language'),
                    asin=asin
                )

            except Exception as e:
                print(f"Warning: Failed to build path from pattern, falling back to flat structure: {e}")
                final_m4b_path = self.library_path / safe_title / f"{safe_title}.m4b"
        else:
            # No product metadata, use flat structure in library
            final_m4b_path = self.library_path / safe_title / f"{safe_title}.m4b"

        # 3. Return paths with temp files in downloads_dir and final M4B in library_path
        return {
            # Temporary files in downloads directory
            'aaxc_file': temp_dir / f"{safe_title}.aaxc",
            'voucher_file': temp_dir / f"{safe_title}.json",
            'simple_voucher_file': temp_dir / f"{safe_title}_simple.json",
            'metadata_file': temp_dir / f"content_metadata_{asin}.json",
            'temp_m4b_file': temp_dir / f"{safe_title}.m4b",
            # Final M4B location in library (following naming pattern)
            'm4b_file': final_m4b_path,
            'temp_dir': temp_dir
        }

    async def _get_download_license(self, client, asin: str, quality: str):
        quality = self._validate_quality_setting(quality)
        license_request = {"drm_type": "Adrm", "consumption_type": "Download", "quality": quality}
        response = await client.post(f"content/{asin}/licenserequest", body=license_request)

        content_license = response.get("content_license", {})
        if content_license.get("status_code") != "Granted":
            raise Exception(f"License denied: {content_license.get('message', 'Unknown error')}")

        return response

    def _get_download_url(self, license_response: Dict) -> str:
        try:
            return license_response["content_license"]["content_metadata"]["content_url"]["offline_url"]
        except KeyError as e:
            raise Exception(f"Could not extract download URL from license: {e}")
    
    async def _download_file(self, url: str, filename: Path, asin: str = None, title: str = None):
        headers = {"User-Agent": "Audible/671 CFNetwork/1240.0.4 Darwin/20.6.0"}
        try:
            async with httpx.AsyncClient(timeout=300.0) as client:
                async with client.stream("GET", url, headers=headers) as response:
                    response.raise_for_status()

                    # Get total file size from headers
                    total_bytes = None
                    content_length = response.headers.get('content-length')
                    if content_length:
                        total_bytes = int(content_length)

                    filename.parent.mkdir(parents=True, exist_ok=True)
                    downloaded_bytes = 0
                    download_start_time = time.time()
                    last_log_time = download_start_time
                    last_logged_percent = 0

                    # Truncate title for display (max 40 chars)
                    display_title = title[:37] + "..." if title and len(title) > 40 else title

                    # Log initial download start
                    if asin and total_bytes:
                        if display_title:
                            self._log(f"📥 [{display_title}] Downloading {self._format_bytes(total_bytes)}...", asin)
                        else:
                            self._log(f"📥 Downloading {self._format_bytes(total_bytes)}...", asin)

                    with open(filename, "wb") as f:
                        async for chunk in response.aiter_bytes(chunk_size=8192):
                            f.write(chunk)
                            downloaded_bytes += len(chunk)

                            # Update progress if we have an asin
                            if asin:
                                # Calculate download speed and ETA
                                current_time = time.time()
                                elapsed = current_time - download_start_time
                                speed = downloaded_bytes / elapsed if elapsed > 0 else 0
                                eta = (total_bytes - downloaded_bytes) / speed if speed > 0 and total_bytes else 0
                                
                                # Update progress with speed and ETA
                                self.update_download_progress(
                                    asin, 
                                    downloaded_bytes, 
                                    total_bytes,
                                    speed=speed,
                                    eta=eta,
                                    elapsed=elapsed
                                )

                                # Log progress every 10% or every 5 seconds
                                if total_bytes and total_bytes > 0:
                                    percent = (downloaded_bytes / total_bytes) * 100
                                    percent_milestone = int(percent / 10) * 10  # Round down to nearest 10%

                                    if (percent_milestone > last_logged_percent and percent_milestone % 10 == 0) or \
                                       (current_time - last_log_time > 5):
                                        downloaded_str = self._format_bytes(downloaded_bytes)
                                        total_str = self._format_bytes(total_bytes)
                                        speed_str = self._format_bytes(speed)

                                        if display_title:
                                            self._log(f"   [{display_title}] {downloaded_str}/{total_str} ({percent:.1f}%) @ {speed_str}/s", asin)
                                        else:
                                            self._log(f"   Progress: {downloaded_str}/{total_str} ({percent:.1f}%) @ {speed_str}/s", asin)
                                        last_log_time = current_time
                                        last_logged_percent = percent_milestone

                    # Log completion with average speed
                    if asin:
                        total_elapsed = time.time() - download_start_time
                        avg_speed = downloaded_bytes / total_elapsed if total_elapsed > 0 else 0
                        avg_speed_str = self._format_bytes(avg_speed)
                        if display_title:
                            self._log(f"✓ [{display_title}] Complete: {self._format_bytes(downloaded_bytes)} (avg {avg_speed_str}/s)", asin)
                        else:
                            self._log(f"✓ Download complete: {self._format_bytes(downloaded_bytes)} (avg {avg_speed_str}/s)", asin)

        except Exception as e:
            if filename.exists():
                filename.unlink()
            raise e
    
    async def download_book(self, book_asin: str, book_title: str, quality: str = "High", cleanup_aax: bool = True, max_retries: int = 3, product: Dict = None) -> Optional[str]:
        if not self.auth:
            raise Exception("Authentication required.")

        # Track start time for this book
        self.download_start_times[book_asin] = time.time()

        paths = self._get_file_paths(book_title, book_asin, product)
        m4b_file = paths['m4b_file']

        # Check if book already in library (using stored file_path from library.json)
        existing_entry = self.get_library_entry(book_asin)
        if existing_entry.get('state') == DownloadState.CONVERTED.value:
            # Check stored file path first
            stored_path = existing_entry.get('file_path')
            if stored_path and Path(stored_path).exists():
                self._log(f"✅ '{book_title}' already in library: {Path(stored_path).name}", book_asin)
                return str(stored_path)
            elif m4b_file.exists():
                # Fallback: check expected path based on current naming pattern
                self._log(f"✅ '{book_title}' already in library: {m4b_file.name}", book_asin)
                # Update stored path to current location
                self.add_to_library(book_asin, book_title, str(m4b_file))
                return str(m4b_file)
            else:
                # File is missing, clear state and re-download
                self._log(f"⚠️  '{book_title}' was downloaded but file is missing. Re-downloading...", book_asin)
                self.library_state.pop(book_asin, None)
                self._save_library_state()

        # Fuzzy duplicate check (for different ASINs but same book, e.g., regional editions)
        # Only checks within the SAME library to allow different language versions in separate libraries
        if product:
            book_authors = product.get('authors', '')
            if isinstance(book_authors, list):
                book_authors = ', '.join([a.get('name', '') if isinstance(a, dict) else str(a) for a in book_authors])

            fuzzy_match = self._check_fuzzy_duplicate(book_title, book_authors, str(self.library_path), threshold=0.85)
            if fuzzy_match:
                match_asin, match_path, similarity = fuzzy_match
                self._log(f"⚠️  Potential duplicate in this library (similarity: {similarity:.0%})", book_asin)
                self._log(f"    '{book_title}' may already exist as '{Path(match_path).name}'", book_asin)
                self._log(f"    Skipping download. Different libraries won't trigger this check.", book_asin)
                return match_path

        self._log(f"🎧 Starting: '{book_title}' (Quality: {quality})", book_asin)
        self.set_download_state(book_asin, DownloadState.PENDING, title=book_title)

        paths['aaxc_file'].parent.mkdir(parents=True, exist_ok=True)

        for attempt in range(max_retries):
            async with self.download_semaphore:
                try:
                    result = await self._process_book_download(book_asin, book_title, quality, paths, cleanup_aax)
                    # Cleanup start time on success
                    if book_asin in self.download_start_times:
                        del self.download_start_times[book_asin]
                    return result
                except Exception as e:
                    self._log(f"❌ Error on attempt {attempt + 1}/{max_retries}: {e}", book_asin)
                    if attempt < max_retries - 1:
                        self._log(f"⏳ Retrying in 5 seconds...", book_asin)
                        self.set_download_state(
                            book_asin, 
                            DownloadState.RETRYING, 
                            error=str(e),
                            error_type=type(e).__name__,
                            attempt=attempt + 1,
                            max_retries=max_retries
                        )
                        await asyncio.sleep(5)
                    else:
                        self._log(f"💔 Failed after {max_retries} attempts", book_asin)
                        self.set_download_state(
                            book_asin, 
                            DownloadState.ERROR, 
                            error=str(e),
                            error_type=type(e).__name__,
                            failed_at=time.time(),
                            attempts=max_retries
                        )
                        # Cleanup start time on failure
                        if book_asin in self.download_start_times:
                            del self.download_start_times[book_asin]
                        return None
        return None
    
    async def _process_book_download(self, asin: str, title: str, quality: str, paths: Dict[str, Path], cleanup_aax: bool) -> Optional[str]:
        async with audible.AsyncClient(auth=self.auth) as client:
            aaxc_file = paths['aaxc_file']
            temp_m4b_file = paths['temp_m4b_file']
            final_m4b_file = paths['m4b_file']

            # Check if already in library
            if final_m4b_file.exists():
                self._log(f"✅ Already in library: {final_m4b_file.name}", asin)
                self.add_to_library(asin, title, str(final_m4b_file))
                self.set_download_state(asin, DownloadState.CONVERTED, title=title, file_path=str(final_m4b_file))
                return str(final_m4b_file)

            # Download AAX file to temp directory if not already downloaded
            if not aaxc_file.exists():
                self._log(f"🔐 Requesting download license...", asin)
                self.set_download_state(asin, DownloadState.LICENSE_REQUESTED)
                license_response = await self._get_download_license(client, asin, quality)
                self.set_download_state(asin, DownloadState.LICENSE_GRANTED)
                self._log(f"✓ License granted", asin)

                self.set_download_state(asin, DownloadState.DOWNLOADING)
                download_url = self._get_download_url(license_response)
                await self._download_file(download_url, aaxc_file, asin, title)

                if not aaxc_file.exists() or aaxc_file.stat().st_size == 0:
                    raise Exception("Download failed: file is missing or empty.")

                # Save license and decrypt voucher
                paths['voucher_file'].write_text(json.dumps(license_response, indent=4))
                decrypted_voucher = self._decrypt_voucher(asin, license_response)
                if decrypted_voucher:
                    paths['simple_voucher_file'].write_text(json.dumps(decrypted_voucher, indent=4))
                    self._log(f"🔑 License decrypted successfully", asin)

                await self._export_content_metadata(client, asin, aaxc_file.parent, license_response)
                self.set_download_state(asin, DownloadState.DOWNLOAD_COMPLETE)
            else:
                self._log(f"✓ AAX file already exists, skipping download", asin)

            # Convert AAX to M4B in temp directory
            if not temp_m4b_file.exists():
                async with self.decrypt_semaphore:
                    self.set_download_state(asin, DownloadState.DECRYPTING)
                    self._log(f"🔄 Converting to M4B format...", asin)
                    await self._convert_to_m4b(aaxc_file, temp_m4b_file, asin)
                    self._log(f"✓ Conversion complete", asin)

                    self._log(f"✍️  Adding metadata...", asin)
                    await self._add_enhanced_metadata(client, temp_m4b_file, asin)
            else:
                self._log(f"✓ M4B file already exists, skipping conversion", asin)

            # Move M4B from temp to final library location
            self._log(f"📁 Moving to library...", asin)
            self._move_to_library(temp_m4b_file, final_m4b_file, title, asin)

            # Add to library state (persisted to library.json for duplicate detection)
            self.add_to_library(asin, title, str(final_m4b_file))
            
            # Update queue manager state to CONVERTED (important for UI progress tracking)
            self.set_download_state(asin, DownloadState.CONVERTED, title=title, file_path=str(final_m4b_file))

            # Cleanup temporary files if requested
            if cleanup_aax:
                self._log(f"🧹 Cleaning up temporary files...", asin)
                self._cleanup_temp_files(paths, asin)

            # Calculate total elapsed time
            if asin in self.download_start_times:
                elapsed = time.time() - self.download_start_times[asin]
                elapsed_str = self._format_elapsed_time(elapsed)
                self._log(f"✅ Completed in {elapsed_str}!", asin)

            return str(final_m4b_file)

    def _move_to_library(self, temp_m4b_file: Path, final_m4b_file: Path, title: str, asin: str = None):
        """Move the converted M4B file from temp directory to final library location."""
        if not temp_m4b_file.exists():
            raise Exception(f"Temporary M4B file not found: {temp_m4b_file}")

        # Create parent directory for final M4B file
        final_m4b_file.parent.mkdir(parents=True, exist_ok=True)

        # Move the file
        try:
            shutil.move(str(temp_m4b_file), str(final_m4b_file))
            self._log(f"✓ Moved to: {final_m4b_file.relative_to(self.library_path)}", asin)
        except Exception as e:
            raise Exception(f"Failed to move M4B to library: {e}")

    def _cleanup_temp_files(self, paths: Dict[str, Path], asin: str = None):
        """Clean up temporary download files, keeping only the final M4B in library."""
        temp_dir = paths.get('temp_dir')
        if not temp_dir or not temp_dir.exists():
            return

        # Remove all files in temp directory
        files_deleted = 0
        for key, path in paths.items():
            if key not in ['m4b_file', 'temp_dir'] and path.exists():
                try:
                    path.unlink()
                    files_deleted += 1
                except OSError as e:
                    self._log(f"⚠️  Could not delete {path.name}: {e}", asin)

        # Try to remove the temp directory if empty
        try:
            if temp_dir.exists() and not any(temp_dir.iterdir()):
                temp_dir.rmdir()
                self._log(f"✓ Cleaned up {files_deleted} temporary file(s)", asin)
        except OSError as e:
            self._log(f"⚠️  Could not remove temp directory: {e}", asin)

    def _check_ffmpeg(self):
        try:
            subprocess.run(['ffmpeg', '-version'], capture_output=True, text=True, check=True, timeout=10)
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            raise Exception("FFmpeg not found or not executable. Please install FFmpeg.")

    def _validate_quality_setting(self, quality: str) -> str:
        quality_map = {"extreme": "High", "high": "High", "normal": "Normal", "standard": "Normal"}
        normalized_quality = quality_map.get(quality.lower(), quality)
        if normalized_quality not in ["High", "Normal"]:
            self._log(f"⚠️  Invalid quality '{quality}'. Using 'High'.")
            return "High"
        return normalized_quality

    async def _convert_to_m4b(self, aaxc_file: Path, m4b_file: Path, asin: str = None):
        self._check_ffmpeg()

        simple_voucher_file = aaxc_file.with_suffix('.json').with_name(aaxc_file.stem + '_simple.json')
        if not simple_voucher_file.exists():
            raise Exception(f"Decrypted voucher file not found: {simple_voucher_file}")

        try:
            voucher_data = json.loads(simple_voucher_file.read_text())
            key = voucher_data["key"]
            iv = voucher_data["iv"]
        except (KeyError, json.JSONDecodeError) as e:
            raise Exception(f"Could not read key/iv from voucher file: {e}")

        cmd = [
            'ffmpeg', '-v', 'quiet', '-stats', '-y',
            '-audible_key', key, '-audible_iv', iv,
            '-i', str(aaxc_file), '-c', 'copy', str(m4b_file)
        ]

        try:
            process = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            _, stderr = await process.communicate()
            if process.returncode != 0:
                raise Exception(f"FFmpeg conversion failed: {stderr.decode()}")
        except Exception as e:
            if m4b_file.exists():
                m4b_file.unlink()
            raise e

    async def _export_content_metadata(self, client, asin: str, book_dir: Path, license_response: Dict):
        try:
            content_metadata = license_response.get("content_license", {}).get("content_metadata", {})
            metadata_file = book_dir / f"content_metadata_{asin}.json"
            metadata_file.write_text(json.dumps(content_metadata, indent=2))
        except Exception as e:
            self._log(f"⚠️  Could not export content metadata: {e}", asin)
    
    async def _add_enhanced_metadata(self, client, m4b_file: Path, asin: str):
        try:
            book_details = await client.get(f"catalog/products/{asin}", params={"response_groups": "product_attrs,product_desc,contributors,media,series"})
            product = book_details.get('product', {})
            audiobook = MP4(str(m4b_file))

            # Title
            if product.get('title'):
                audiobook['©nam'] = [product['title']]
                audiobook['©alb'] = [product['title']]
            
            # Subtitle
            if product.get('subtitle'):
                audiobook['----:com.apple.iTunes:SUBTITLE'] = [product['subtitle'].encode('utf-8')]
            
            # Authors
            if product.get('authors'):
                audiobook['©ART'] = [', '.join(a['name'] for a in product['authors'])]
            
            # Narrators (use custom iTunes tag, NOT ©gen which is Genre)
            if product.get('narrators'):
                narrator_str = ', '.join(n['name'] for n in product['narrators'])
                audiobook['----:com.apple.iTunes:NARRATOR'] = [narrator_str.encode('utf-8')]
            
            # Publisher
            if product.get('publisher_name'):
                audiobook['©pub'] = [product['publisher_name']]
            
            # Release date and year
            if product.get('release_date'):
                audiobook['©day'] = [product['release_date']]
                # Extract year for publish year field
                year = product['release_date'].split('-')[0]
                audiobook['©yer'] = [year]
            
            # Description
            if product.get('publisher_summary'):
                audiobook['desc'] = [product['publisher_summary'][:255]]
            
            # Series
            if product.get('series'):
                series = product['series'][0]
                audiobook['©grp'] = [f"{series['title']} #{series['sequence']}"]
            
            # Language
            if product.get('language'):
                audiobook['----:com.apple.iTunes:LANGUAGE'] = [product['language'].encode('utf-8')]
            
            # ISBN (if available)
            if product.get('isbn'):
                audiobook['----:com.apple.iTunes:ISBN'] = [product['isbn'].encode('utf-8')]
            
            # ASIN
            audiobook['©cmt'] = [f"ASIN: {asin}"]
            audiobook['----:com.apple.iTunes:ASIN'] = [asin.encode('utf-8')]
            
            # Media type (2 = Audiobook)
            audiobook['stik'] = [2]
            
            audiobook.save()
            self._log(f"✓ Metadata added successfully", asin)
        except Exception as e:
            self._log(f"⚠️  Could not add enhanced metadata: {e}", asin)

async def download_books(account_name, region, selected_books, quality="High", cleanup_aax=True, max_retries=3, library_path=None, downloads_dir=None):
    """
    Download multiple audiobooks.

    Args:
        account_name: Audible account name
        region: Audible region (e.g., 'us', 'uk')
        selected_books: List of books to download
        quality: Audio quality ('High' or 'Normal')
        cleanup_aax: Whether to cleanup temporary files after conversion
        max_retries: Maximum number of retry attempts
        library_path: Final library path where M4B files will be stored
        downloads_dir: Temporary download directory (defaults to 'downloads/')
    """
    if not library_path:
        raise ValueError("library_path is required. Please configure a library before downloading.")

    downloader = AudiobookDownloader(
        account_name,
        region,
        library_path=library_path,
        downloads_dir=downloads_dir
    )

    # Log batch summary
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] ========================================")
    print(f"[{timestamp}] 📚 Starting batch download of {len(selected_books)} book(s)")
    print(f"[{timestamp}] 📂 Library: {library_path}")
    print(f"[{timestamp}] ========================================")

    start_time = time.time()
    tasks = [downloader.download_book(book['asin'], book['title'], book.get('quality', quality), cleanup_aax, max_retries, book) for book in selected_books]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Log batch summary
    elapsed = time.time() - start_time
    elapsed_str = AudiobookDownloader._format_elapsed_time(elapsed)
    successful = sum(1 for r in results if r and not isinstance(r, Exception))
    failed = len(results) - successful

    end_timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{end_timestamp}] ========================================")
    print(f"[{end_timestamp}] 📊 Batch complete in {elapsed_str}")
    print(f"[{end_timestamp}] ✅ Successful: {successful}/{len(selected_books)}")
    if failed > 0:
        print(f"[{end_timestamp}] ❌ Failed: {failed}/{len(selected_books)}")
    print(f"[{end_timestamp}] ========================================")

    return results