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
from app.services.settings_service import get_naming_pattern
from datetime import datetime
from utils.fuzzy_matching import normalize_for_matching, calculate_similarity
from app.config.constants import CONFIG_DIR, DOWNLOAD_QUEUE_FILE, get_auth_file_path
from app.models import DownloadState
from app.services import PathBuilder, AudioConverter, MetadataEnricher, LibraryManager
from utils.queue_base import BaseQueueManager


class DownloadQueueManager(BaseQueueManager):
    """
    Singleton manager for download queue and progress tracking.
    Provides persistent state storage shared across all downloader instances.
    """

    def __init__(self):
        # Initialize base class with queue file path
        super().__init__(DOWNLOAD_QUEUE_FILE)

    def _generate_batch_id(self) -> str:
        """Generate a unique batch ID for downloads"""
        return f"batch_{int(time.time())}"

    def _get_item_id_key(self) -> str:
        """Get the key name for download items"""
        return 'asin'

    def _log_warning(self, message: str):
        """Log warning message"""
        print(f"Warning: {message}")

    # Download-specific convenience methods
    def get_all_downloads(self) -> Dict:
        """Get all downloads in the queue (excluding batch info)"""
        return self.get_all_items()

    def get_download(self, asin: str) -> Optional[Dict]:
        """Get a specific download by ASIN"""
        return self.get_item(asin)

    def update_download(self, asin: str, updates: Dict):
        """Update download state"""
        self.update_item(asin, updates)

    def add_download_to_queue(self, asin: str, title: str, **metadata):
        """Add a new download to the queue"""
        self.add_to_queue(asin, title, DownloadState.PENDING.value, **metadata)

    def get_statistics(self) -> Dict:
        """Get download statistics"""
        batch_info = self.get_batch_info()
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
                self.mark_batch_complete()
                stats['batch_complete'] = True

        return stats

    def clear_completed(self, older_than_hours: int = 24):
        """Remove completed downloads older than specified hours"""
        return self.clear_old_items(older_than_hours)

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

        # Initialize service classes
        self.path_builder = PathBuilder()
        self.audio_converter = AudioConverter()
        self.metadata_enricher = MetadataEnricher()
        self.library_manager = LibraryManager(self.library_path, self.account_name)

        # Maintain backward compatibility - expose library_state through library_manager
        self.library_state = self.library_manager.library_state
        self.library_file = self.library_manager.library_file

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
        auth_file = get_auth_file_path(self.account_name)
        if auth_file.exists():
            return audible.Authenticator.from_file(auth_file)
        return None

    def _load_auth_details(self) -> Optional[Dict]:
        """Loads the raw auth JSON file for details not exposed by the authenticator."""
        auth_file = get_auth_file_path(self.account_name)
        if auth_file.exists():
            return json.loads(auth_file.read_text())
        return None

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
        return self.library_manager.get_library_entry(asin)

    def add_to_library(self, asin: str, title: str, file_path: str, **metadata):
        """Add a book to the library state and persist to disk"""
        self.library_manager.add_to_library(asin, title, file_path, **metadata)
        # Update the exposed library_state for backward compatibility
        self.library_state = self.library_manager.library_state

    def set_download_state(self, asin: str, state: DownloadState, **metadata):
        # Check if this is a new download
        existing = self.queue_manager.get_download(asin)

        if not existing:
            # New download - add to queue with batch tracking
            title = metadata.get('title', 'Unknown')
            self.queue_manager.add_download_to_queue(asin, title, downloaded_by_account=self.account_name)

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

    def _check_fuzzy_duplicate(self, book_title: str, book_authors: str, target_library_path: str, threshold: float = 0.85) -> Optional[Tuple[str, str, float]]:
        """Delegate to LibraryManager for fuzzy duplicate checking"""
        return self.library_manager.check_fuzzy_duplicate(book_title, book_authors, target_library_path, threshold)

    @staticmethod
    def extract_asin_from_m4b(file_path: Path) -> Optional[str]:
        """Delegate to MetadataEnricher for ASIN extraction"""
        return MetadataEnricher.extract_asin_from_m4b(file_path)

    def sync_library(self) -> Dict:
        """Delegate to LibraryManager for library syncing"""
        stats = self.library_manager.sync_library()
        # Update the exposed library_state for backward compatibility
        self.library_state = self.library_manager.library_state
        return stats

    def _get_file_paths(self, book_title: str, asin: str, product: Dict = None) -> Dict[str, Path]:
        """Delegate to PathBuilder for file path construction"""
        return self.path_builder.get_file_paths(
            self.downloads_dir,
            self.library_path,
            book_title,
            asin,
            product
        )

    async def _get_download_license(self, client, asin: str, quality: str):
        quality = self.audio_converter.validate_quality_setting(quality)
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
                    await self.audio_converter.convert_to_m4b(aaxc_file, temp_m4b_file)
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

    async def _export_content_metadata(self, client, asin: str, book_dir: Path, license_response: Dict):
        """Delegate to MetadataEnricher for content metadata export"""
        await self.metadata_enricher.export_content_metadata(client, asin, book_dir, license_response)

    async def _add_enhanced_metadata(self, client, m4b_file: Path, asin: str):
        """Delegate to MetadataEnricher for enhanced metadata"""
        await self.metadata_enricher.add_enhanced_metadata(client, m4b_file, asin)

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
