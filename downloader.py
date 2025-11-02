import asyncio
import audible
import subprocess
from pathlib import Path
import os
import re
import json
from enum import Enum
from mutagen.mp4 import MP4
import httpx
import base64
from Crypto.Cipher import AES
from asyncio import Semaphore
import time
import hashlib
from typing import Optional, Dict, List
from settings import get_naming_pattern

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

class AudiobookDownloader:
    def __init__(self, account_name, region="us", max_concurrent_downloads=3, library_path=None):
        self.account_name = account_name
        self.region = region

        if not library_path:
            raise ValueError("library_path is required. Please configure a library before downloading.")

        self.downloads_dir = Path(library_path)
        self.downloads_dir.mkdir(parents=True, exist_ok=True)
        self.download_semaphore = Semaphore(max_concurrent_downloads)
        self.decrypt_semaphore = Semaphore(1)

        self.auth = self._load_authenticator()
        self._auth_details = self._load_auth_details() if self.auth else None

        self.state_file = self.downloads_dir / "download_states.json"
        self.download_states = self._load_states()

    def _load_authenticator(self) -> Optional[audible.Authenticator]:
        """Loads the authenticator object from file."""
        auth_file = Path(f".audible_{self.account_name}") / "auth.json"
        if auth_file.exists():
            return audible.Authenticator.from_file(auth_file)
        return None

    def _load_auth_details(self) -> Optional[Dict]:
        """Loads the raw auth JSON file for details not exposed by the authenticator."""
        auth_file = Path(f".audible_{self.account_name}") / "auth.json"
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
            print(f"❌ Failed to decrypt voucher: {e}")
            return None

    def _load_states(self) -> Dict:
        if self.state_file.exists():
            try:
                return json.load(self.state_file.open('r'))
            except (json.JSONDecodeError, IOError):
                return {}
        return {}
    
    def _save_states(self):
        try:
            with self.state_file.open('w') as f:
                json.dump(self.download_states, f, indent=2)
        except IOError as e:
            print(f"Failed to save states: {e}")
    
    def get_download_state(self, asin: str) -> Dict:
        return self.download_states.get(asin, {})
    
    def set_download_state(self, asin: str, state: DownloadState, **metadata):
        if asin not in self.download_states:
            self.download_states[asin] = {}
        self.download_states[asin].update({'state': state.value, 'timestamp': time.time(), **metadata})
        self._save_states()
    
    def update_download_progress(self, asin: str, downloaded_bytes: int, total_bytes: int = None, **metadata):
        """Update download progress without changing state"""
        if asin not in self.download_states:
            self.download_states[asin] = {}
        
        progress_data = {
            'downloaded_bytes': downloaded_bytes,
            'progress_timestamp': time.time(),
            **metadata
        }
        
        if total_bytes is not None:
            progress_data['total_bytes'] = total_bytes
            progress_data['progress_percent'] = min(100, (downloaded_bytes / total_bytes) * 100) if total_bytes > 0 else 0
        
        self.download_states[asin].update(progress_data)
        self._save_states()
    
    def _sanitize_filename(self, filename):
        return re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f-\x9f]', '_', filename)[:200]

    def _format_author(self, authors) -> str:
        """Format author name(s) from various input formats."""
        if isinstance(authors, str):
            return authors if authors else "Unknown Author"
        elif isinstance(authors, list) and authors:
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

        # Replace placeholders in pattern
        path_str = pattern
        for placeholder, value in replacements.items():
            path_str = path_str.replace(placeholder, value)

        # Clean up path: remove empty segments and consecutive slashes
        path_parts = []
        for part in path_str.split('/'):
            part = part.strip()
            if part:  # Skip empty segments (happens when optional placeholders are empty)
                # Sanitize each path component
                sanitized = self._sanitize_filename(part)
                if sanitized and sanitized != ".m4b":  # Don't add segments that are just the extension
                    path_parts.append(sanitized)

        # Build final path
        if not path_parts:
            # Fallback to flat structure if pattern results in empty path
            safe_title = self._sanitize_filename(title)
            return Path(base_path) / safe_title / f"{safe_title}.m4b"

        # Construct path: all parts except the last are folders, last is the filename
        if len(path_parts) == 1:
            # Only filename provided, no folder structure
            # Create a folder with the title name
            safe_title = self._sanitize_filename(title)
            folder_path = Path(base_path) / safe_title
            # Use the pattern-generated filename
            return folder_path / path_parts[0]
        else:
            # Multiple parts: folders + filename
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
        # Build directory path using the naming pattern from settings
        if product:
            try:
                # Use the new pattern-based path builder
                # Prefer series_data (full structure with sequence) over series (string)
                series_info = product.get('series_data') or product.get('series')

                full_path = self.build_path_from_pattern(
                    base_path=str(self.downloads_dir),
                    title=book_title,
                    authors=product.get('authors', []),
                    narrators=product.get('narrator') or product.get('narrators', []),
                    series=series_info,
                    release_date=product.get('release_date'),
                    publisher=product.get('publisher'),
                    language=product.get('language'),
                    asin=asin
                )
                # Extract directory (parent) from full path
                book_dir = full_path.parent
                # The filename from the pattern (should end with .m4b)
                pattern_filename = full_path.name

                # If pattern filename doesn't include extension, use safe title
                if not pattern_filename.endswith('.m4b'):
                    pattern_filename = self._sanitize_filename(book_title) + '.m4b'

                # Strip .m4b extension to get base name for other files
                base_name = pattern_filename[:-4] if pattern_filename.endswith('.m4b') else pattern_filename

            except Exception as e:
                print(f"Warning: Failed to build path from pattern, falling back to flat structure: {e}")
                safe_title = self._sanitize_filename(book_title)
                book_dir = self.downloads_dir / safe_title
                base_name = safe_title
                pattern_filename = f"{safe_title}.m4b"
        else:
            # No product metadata, use flat structure
            safe_title = self._sanitize_filename(book_title)
            book_dir = self.downloads_dir / safe_title
            base_name = safe_title
            pattern_filename = f"{safe_title}.m4b"

        return {
            'aaxc_file': book_dir / f"{base_name}.aaxc",
            'voucher_file': book_dir / f"{base_name}.json",
            'simple_voucher_file': book_dir / f"{base_name}_simple.json",
            'm4b_file': book_dir / pattern_filename,
            'metadata_file': book_dir / f"content_metadata_{asin}.json"
        }

    async def _get_download_license(self, client, asin: str, quality: str):
        quality = self._validate_quality_setting(quality)
        license_request = {"drm_type": "Adrm", "consumption_type": "Download", "quality": quality}
        print(f"Requesting license for {asin} with quality {quality}")
        response = await client.post(f"content/{asin}/licenserequest", body=license_request)
        
        content_license = response.get("content_license", {})
        if content_license.get("status_code") != "Granted":
            raise Exception(f"License denied: {content_license.get('message', 'Unknown error')}")
        
        print(f"License granted for {asin}")
        return response

    def _get_download_url(self, license_response: Dict) -> str:
        try:
            return license_response["content_license"]["content_metadata"]["content_url"]["offline_url"]
        except KeyError as e:
            raise Exception(f"Could not extract download URL from license: {e}")
    
    async def _download_file(self, url: str, filename: Path, asin: str = None):
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
                    
                    with open(filename, "wb") as f:
                        async for chunk in response.aiter_bytes(chunk_size=8192):
                            f.write(chunk)
                            downloaded_bytes += len(chunk)
                            
                            # Update progress if we have an asin
                            if asin:
                                self.update_download_progress(asin, downloaded_bytes, total_bytes)
        except Exception as e:
            if filename.exists():
                filename.unlink()
            raise e
    
    async def download_book(self, book_asin: str, book_title: str, quality: str = "High", cleanup_aax: bool = True, max_retries: int = 3, product: Dict = None) -> Optional[str]:
        if not self.auth:
            raise Exception("Authentication required.")

        paths = self._get_file_paths(book_title, book_asin, product)
        m4b_file = paths['m4b_file']

        if self.get_download_state(book_asin).get('state') == DownloadState.CONVERTED.value and m4b_file.exists():
            print(f"✅ '{book_title}' already downloaded and converted.")
            return str(m4b_file)

        print(f"📥 Starting download: '{book_title}' (ASIN: {book_asin}) with quality: {quality}")
        self.set_download_state(book_asin, DownloadState.PENDING, title=book_title)

        paths['aaxc_file'].parent.mkdir(parents=True, exist_ok=True)

        for attempt in range(max_retries):
            async with self.download_semaphore:
                try:
                    return await self._process_book_download(book_asin, book_title, quality, paths, cleanup_aax)
                except Exception as e:
                    print(f"❌ Error downloading '{book_title}' on attempt {attempt + 1}: {e}")
                    if attempt < max_retries - 1:
                        print(f"Retrying in 5 seconds...")
                        self.set_download_state(book_asin, DownloadState.RETRYING, error=str(e), attempt=attempt + 1)
                        await asyncio.sleep(5)
                    else:
                        self.set_download_state(book_asin, DownloadState.ERROR, error=str(e))
                        return None
        return None
    
    async def _process_book_download(self, asin: str, title: str, quality: str, paths: Dict[str, Path], cleanup_aax: bool) -> Optional[str]:
        async with audible.AsyncClient(auth=self.auth) as client:
            aaxc_file = paths['aaxc_file']

            if not aaxc_file.exists():
                self.set_download_state(asin, DownloadState.LICENSE_REQUESTED)
                license_response = await self._get_download_license(client, asin, quality)
                self.set_download_state(asin, DownloadState.LICENSE_GRANTED)
                
                self.set_download_state(asin, DownloadState.DOWNLOADING)
                download_url = self._get_download_url(license_response)
                await self._download_file(download_url, aaxc_file, asin)
                
                if not aaxc_file.exists() or aaxc_file.stat().st_size == 0:
                    raise Exception("Download failed: file is missing or empty.")
                
                paths['voucher_file'].write_text(json.dumps(license_response, indent=4))
                print(f"🔑 Saved full license response: {paths['voucher_file'].name}")

                decrypted_voucher = self._decrypt_voucher(asin, license_response)
                if decrypted_voucher:
                    paths['simple_voucher_file'].write_text(json.dumps(decrypted_voucher, indent=4))
                    print(f"🔑 Saved decrypted voucher (key/iv): {paths['simple_voucher_file'].name}")

                await self._export_content_metadata(client, asin, aaxc_file.parent, license_response)
                self.set_download_state(asin, DownloadState.DOWNLOAD_COMPLETE)
            
            m4b_file = paths['m4b_file']
            if not m4b_file.exists():
                async with self.decrypt_semaphore:
                    self.set_download_state(asin, DownloadState.DECRYPTING)
                    await self._convert_to_m4b(aaxc_file, m4b_file)
                    await self._add_enhanced_metadata(client, m4b_file, asin)
            
            self.set_download_state(asin, DownloadState.CONVERTED)
            print(f"✅ '{title}' completed successfully!")

            if cleanup_aax:
                self._cleanup_temp_files(paths)

            return str(m4b_file)

    def _cleanup_temp_files(self, paths: Dict[str, Path]):
        print(f"🧹 Cleaning up temporary files for {paths['aaxc_file'].stem}")
        for key, path in paths.items():
            if key != 'm4b_file' and path.exists():
                try:
                    path.unlink()
                    print(f"🗑️ Deleted {path.name}")
                except OSError as e:
                    print(f"Could not delete {path.name}: {e}")

    def _check_ffmpeg(self):
        try:
            subprocess.run(['ffmpeg', '-version'], capture_output=True, text=True, check=True, timeout=10)
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            raise Exception("FFmpeg not found or not executable. Please install FFmpeg.")

    def _validate_quality_setting(self, quality: str) -> str:
        quality_map = {"extreme": "High", "high": "High", "normal": "Normal", "standard": "Normal"}
        normalized_quality = quality_map.get(quality.lower(), quality)
        if normalized_quality not in ["High", "Normal"]:
            print(f"⚠️ Invalid quality '{quality}'. Using 'High'.")
            return "High"
        return normalized_quality

    async def _convert_to_m4b(self, aaxc_file: Path, m4b_file: Path):
        print(f"🔄 Converting {aaxc_file.name} to M4B...")
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
            print(f"✅ Successfully converted {aaxc_file.name}")
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
            print(f"Could not export content metadata: {e}")
    
    async def _add_enhanced_metadata(self, client, m4b_file: Path, asin: str):
        try:
            book_details = await client.get(f"catalog/products/{asin}", params={"response_groups": "product_attrs,product_desc,contributors,media,series"})
            product = book_details.get('product', {})
            audiobook = MP4(str(m4b_file))
            
            if product.get('title'):
                audiobook['©nam'] = [product['title']]
                audiobook['©alb'] = [product['title']]
            if product.get('authors'):
                audiobook['©ART'] = [', '.join(a['name'] for a in product['authors'])]
            if product.get('narrators'):
                audiobook['©gen'] = [', '.join(n['name'] for n in product['narrators'])]
            if product.get('publisher_name'):
                audiobook['©pub'] = [product['publisher_name']]
            if product.get('release_date'):
                audiobook['©day'] = [product['release_date']]
            if product.get('publisher_summary'):
                audiobook['desc'] = [product['publisher_summary'][:255]]
            if product.get('series'):
                series = product['series'][0]
                audiobook['©grp'] = [f"{series['title']} #{series['sequence']}"]
            
            audiobook['stik'] = [2]
            audiobook['©cmt'] = [f"ASIN: {asin}"]
            audiobook.save()
            print(f"✍️ Enhanced metadata added to {m4b_file.name}")
        except Exception as e:
            print(f"Could not add enhanced metadata: {e}")

async def download_books(account_name, region, selected_books, quality="High", cleanup_aax=True, max_retries=3, library_path=None):
    if not library_path:
        raise ValueError("library_path is required. Please configure a library before downloading.")

    downloader = AudiobookDownloader(account_name, region, library_path=library_path)
    tasks = [downloader.download_book(book['asin'], book['title'], book.get('quality', quality), cleanup_aax, max_retries, book) for book in selected_books]
    return await asyncio.gather(*tasks, return_exceptions=True)