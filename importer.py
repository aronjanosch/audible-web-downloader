"""
M4B Audiobook Importer Module

Scans source directories for M4B files, matches them with Audible metadata,
detects duplicates, and imports files into organized library structure.
"""

import asyncio
import audible
import json
import shutil
import time
import logging
import unicodedata
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from mutagen.mp4 import MP4
from enum import Enum
from utils.fuzzy_matching import normalize_for_matching, calculate_similarity
from utils.audio_metadata import get_mp4_tag

from downloader import AudiobookDownloader
from library_scanner import LocalLibraryScanner
from utils.queue_base import BaseQueueManager
from utils.constants import CONFIG_DIR

logger = logging.getLogger(__name__)


class ImportState(Enum):
    """States for import progress tracking."""
    PENDING = "pending"
    SCANNING = "scanning"
    MATCHING = "matching"
    MATCHED = "matched"
    IMPORTING = "importing"
    COMPLETE = "complete"
    ERROR = "error"
    SKIPPED = "skipped"


class ImportQueueManager(BaseQueueManager):
    """
    Singleton manager for import queue and progress tracking.
    Similar to DownloadQueueManager but for import operations.
    """
    
    def __init__(self):
        # Initialize base class with queue file path
        super().__init__(CONFIG_DIR / "import_queue.json")
    
    def _generate_batch_id(self) -> str:
        """Generate a unique batch ID for imports"""
        return f"import_batch_{int(time.time())}"
    
    def _get_item_id_key(self) -> str:
        """Get the key name for import items"""
        return 'file_path'
    
    def _log_warning(self, message: str):
        """Log warning message"""
        logger.warning(message)
    
    # Import-specific convenience methods
    def get_all_imports(self) -> Dict:
        """Get all imports in the queue (excluding batch info)"""
        return self.get_all_items()
    
    def get_import(self, file_path: str) -> Optional[Dict]:
        """Get a specific import by file path"""
        return self.get_item(file_path)
    
    def update_import(self, file_path: str, updates: Dict):
        """Update import state"""
        self.update_item(file_path, updates)
    
    def start_new_batch(self, expected_count: int = 0):
        """Start a new import batch with an expected file count."""
        batch_id = self._generate_batch_id()
        self._queue['_batch_info'] = {
            'current_batch_id': batch_id,
            'batch_complete': False,
            'batch_start_time': time.time(),
            'expected_count': expected_count,
            'files_added': 0
        }
        self._save_queue()
        return batch_id
    
    def add_import_to_queue(self, file_path: str, title: str, **metadata):
        """Add a new file to the import queue."""
        # Use base class method
        self.add_to_queue(file_path, title, ImportState.PENDING.value, **metadata)
        
        # Increment files added counter
        if '_batch_info' in self._queue:
            self._queue['_batch_info']['files_added'] = self._queue['_batch_info'].get('files_added', 0) + 1
            self._save_queue()
    
    def get_statistics(self) -> Dict:
        """Get import statistics."""
        batch_info = self.get_batch_info()
        current_batch_id = batch_info.get('current_batch_id')
        
        stats = {
            'active': 0,
            'queued': 0,
            'completed': 0,
            'failed': 0,
            'skipped': 0,
            'total_imports': 0,
            'batch_complete': batch_info.get('batch_complete', False),
            'batch_id': current_batch_id
        }
        
        # Count all imports in current batch
        for file_path, import_data in self._queue.items():
            if file_path.startswith('_'):
                continue
            
            # Only count imports from the current batch
            import_batch_id = import_data.get('batch_id')
            if import_batch_id != current_batch_id:
                continue
            
            stats['total_imports'] += 1
            state = import_data.get('state', '')
            
            if state in ['pending', 'scanning']:
                stats['queued'] += 1
            elif state in ['matching', 'matched', 'importing']:
                stats['active'] += 1
            elif state == 'complete':
                stats['completed'] += 1
            elif state == 'error':
                stats['failed'] += 1
            elif state == 'skipped':
                stats['skipped'] += 1
        
        # Check if batch is complete
        # Only mark complete if:
        # 1. We have imports in this batch
        # 2. No active or queued items remain
        # 3. Expected count is met (if specified)
        if stats['total_imports'] > 0 and stats['active'] == 0 and stats['queued'] == 0:
            expected_count = batch_info.get('expected_count', 0)
            # If expected_count is set, verify we have that many files
            # Otherwise fall back to checking if all are done
            can_complete = (expected_count == 0 or stats['total_imports'] >= expected_count)
            
            if can_complete and not batch_info.get('batch_complete', False):
                self.mark_batch_complete()
                stats['batch_complete'] = True
        
        return stats
    
    def clear_completed(self, older_than_hours: int = 24):
        """Remove completed imports older than specified hours."""
        return self.clear_old_items(older_than_hours)


class AudiobookImporter:
    """Manages M4B file import with Audible metadata enrichment."""
    
    def __init__(self, account_name: str, region: str, library_path: str):
        """
        Initialize importer.
        
        Args:
            account_name: Audible account name for authentication
            region: Audible region (e.g., 'us', 'uk', 'de')
            library_path: Target library path for imported files
        """
        self.account_name = account_name
        self.region = region
        self.library_path = Path(library_path)
        
        # Load authentication
        self.auth = self._load_authenticator()
        if not self.auth:
            raise ValueError(f"No authentication found for account '{account_name}'")
        
        # Initialize downloader for reusing methods
        self.downloader = AudiobookDownloader(
            account_name=account_name,
            region=region,
            library_path=str(library_path),
            downloads_dir="downloads"
        )
        
        # Initialize queue manager
        self.queue_manager = ImportQueueManager()
        
        logger.info(f"AudiobookImporter initialized for account '{account_name}' in region '{region}'")
    
    def _load_authenticator(self) -> Optional[audible.Authenticator]:
        """Load Audible authenticator from file."""
        auth_file = Path("config") / "auth" / self.account_name / "auth.json"
        if auth_file.exists():
            return audible.Authenticator.from_file(auth_file)
        return None
    
    def scan_directory(self, source_path: str) -> List[Dict]:
        """
        Recursively scan directory for M4B files.
        
        Args:
            source_path: Source directory to scan
            
        Returns:
            List of file info dictionaries
        """
        source_path = Path(source_path)
        
        if not source_path.exists():
            raise ValueError(f"Source path does not exist: {source_path}")
        
        if not source_path.is_dir():
            raise ValueError(f"Source path is not a directory: {source_path}")
        
        files = []
        
        # Recursively find all M4B files
        for m4b_file in source_path.rglob('*.m4b'):
            try:
                file_info = self.extract_file_metadata(m4b_file)
                files.append(file_info)
                logger.info(f"Found: {m4b_file.name}")
            except Exception as e:
                logger.error(f"Error scanning {m4b_file}: {e}")
        
        logger.info(f"Scanned {len(files)} M4B files from {source_path}")
        return files
    
    def extract_file_metadata(self, file_path: Path) -> Dict:
        """
        Extract metadata from M4B file using Mutagen.
        
        Args:
            file_path: Path to M4B file
            
        Returns:
            Dictionary with file info and metadata
        """
        try:
            audio_file = MP4(str(file_path))
            
            # Extract basic metadata
            title = get_mp4_tag(audio_file, '©nam') or file_path.stem
            author = get_mp4_tag(audio_file, '©ART') or get_mp4_tag(audio_file, 'aART')
            narrator = get_mp4_tag(audio_file, '----:com.apple.iTunes:NARRATOR')

            # Check for existing ASIN
            asin = None
            comment = get_mp4_tag(audio_file, '©cmt')
            if comment:
                asin_match = re.search(r'ASIN:\s*([A-Z0-9]{10})', comment)
                if asin_match:
                    asin = asin_match.group(1)

            if not asin:
                asin = get_mp4_tag(audio_file, '----:com.apple.iTunes:ASIN')
            
            # Get file stats
            file_stat = file_path.stat()
            
            return {
                'file_path': str(file_path),
                'file_name': file_path.name,
                'file_size': file_stat.st_size,
                'title': title,
                'author': author,
                'narrator': narrator,
                'asin': asin,
                'duration': getattr(audio_file.info, 'length', 0)
            }
            
        except Exception as e:
            logger.error(f"Error extracting metadata from {file_path}: {e}")
            # Return minimal info
            return {
                'file_path': str(file_path),
                'file_name': file_path.name,
                'file_size': file_path.stat().st_size,
                'title': file_path.stem,
                'author': None,
                'narrator': None,
                'asin': None,
                'duration': 0,
                'error': str(e)
            }
    
    async def search_audible_catalog(self, title: str, author: str = None, num_results: int = 5) -> List[Dict]:
        """
        Search Audible catalog by title and author.
        
        Args:
            title: Book title to search for
            author: Optional author name
            num_results: Number of results to return (default 5)
            
        Returns:
            List of Audible product dictionaries
        """
        try:
            async with audible.AsyncClient(auth=self.auth) as client:
                # Build search query
                search_query = title
                if author:
                    search_query = f"{title} {author}"
                
                params = {
                    "keywords": search_query,
                    "num_results": num_results,
                    "products_sort_by": "Relevance",
                    "response_groups": "product_attrs,contributors,media,series,product_desc"
                }
                
                response = await client.get("1.0/catalog/products", params=params)
                products = response.get("products", [])
                
                logger.info(f"Found {len(products)} results for '{search_query}'")
                return products
                
        except Exception as e:
            logger.error(f"Error searching Audible catalog: {e}")
            return []
    
    async def match_with_audible(self, file_info: Dict) -> Dict:
        """
        Search Audible for matching book based on title + author.
        
        Args:
            file_info: File metadata dictionary
            
        Returns:
            Match result dictionary with matches, confidence, and status
        """
        title = file_info.get('title', '')
        author = file_info.get('author', '')
        
        if not title:
            return {
                'file_info': file_info,
                'matches': [],
                'confidence': 0.0,
                'selected_match': None,
                'status': 'not_found',
                'reason': 'No title found in file metadata'
            }
        
        # Search Audible
        matches = await self.search_audible_catalog(title, author)
        
        if not matches:
            return {
                'file_info': file_info,
                'matches': [],
                'confidence': 0.0,
                'selected_match': None,
                'status': 'not_found',
                'reason': 'No matches found on Audible'
            }
        
        # Calculate confidence for each match
        match_scores = []
        for match in matches:
            confidence = self.calculate_match_confidence(file_info, match)
            match_scores.append((match, confidence))
        
        # Sort by confidence
        match_scores.sort(key=lambda x: x[1], reverse=True)
        best_match, best_confidence = match_scores[0]
        
        # Auto-select if confidence is high
        selected_match = None
        status = 'uncertain'
        
        if best_confidence >= 0.85:
            selected_match = best_match
            status = 'matched'
        
        return {
            'file_info': file_info,
            'matches': [m for m, _ in match_scores],
            'match_confidences': {m.get('asin'): c for m, c in match_scores},
            'confidence': best_confidence,
            'selected_match': selected_match,
            'status': status,
            'reason': f'Best match confidence: {best_confidence:.2%}'
        }
    
    def calculate_match_confidence(self, file_metadata: Dict, audible_product: Dict) -> float:
        """
        Calculate confidence score for Audible match.
        
        Args:
            file_metadata: File metadata dictionary
            audible_product: Audible product dictionary
            
        Returns:
            Confidence score between 0 and 1
        """
        # Normalize titles
        file_title = normalize_for_matching(file_metadata.get('title', ''))
        audible_title = normalize_for_matching(audible_product.get('title', ''))

        # Calculate title similarity
        title_sim = calculate_similarity(file_title, audible_title)

        # Normalize authors
        file_author = normalize_for_matching(file_metadata.get('author', ''))
        audible_authors = audible_product.get('authors', [])
        audible_author_str = self.downloader._format_author(audible_authors)
        audible_author = normalize_for_matching(audible_author_str)

        # Calculate author similarity
        author_sim = calculate_similarity(file_author, audible_author) if file_author else 0.5

        # Weighted combination (title is more important)
        confidence = (title_sim * 0.6) + (author_sim * 0.4)

        # Bonus if narrator matches
        file_narrator = file_metadata.get('narrator')
        audible_narrators = audible_product.get('narrators', [])

        if file_narrator and audible_narrators:
            file_narrator_norm = normalize_for_matching(file_narrator)
            audible_narrator_str = self.downloader._format_narrator(audible_narrators)
            audible_narrator_norm = normalize_for_matching(audible_narrator_str)

            narrator_sim = calculate_similarity(file_narrator_norm, audible_narrator_norm)
            confidence = min(1.0, confidence + narrator_sim * 0.1)
        
        return confidence
    
    def check_duplicate(self, file_info: Dict, audible_match: Optional[Dict] = None) -> Optional[Dict]:
        """
        Check for duplicates in target library.
        
        Args:
            file_info: File metadata dictionary
            audible_match: Optional Audible product match
            
        Returns:
            None if no duplicate, or dictionary with duplicate info
        """
        # Check for exact ASIN match
        asin = None
        
        # First check if file has ASIN
        if file_info.get('asin'):
            asin = file_info['asin']
        # Then check if we have a matched Audible product
        elif audible_match and audible_match.get('asin'):
            asin = audible_match['asin']
        
        if asin:
            library_entry = self.downloader.get_library_entry(asin)
            if library_entry and library_entry.get('state') == 'converted':
                stored_path = library_entry.get('file_path', '')
                return {
                    'type': 'exact_asin',
                    'reason': f"Book with ASIN {asin} already in library",
                    'existing_path': stored_path,
                    'asin': asin
                }
        
        # Check for fuzzy duplicate
        title = file_info.get('title', '')
        author = file_info.get('author', '')
        
        if audible_match:
            # Use Audible metadata for better matching
            title = audible_match.get('title', title)
            authors = audible_match.get('authors', [])
            author = self.downloader._format_author(authors) if authors else author
        
        if title and author:
            fuzzy_match = self.downloader._check_fuzzy_duplicate(
                title, author, str(self.library_path), threshold=0.85
            )
            
            if fuzzy_match:
                match_asin, match_path, similarity = fuzzy_match
                return {
                    'type': 'fuzzy',
                    'reason': f"Similar book found (similarity: {similarity:.0%})",
                    'existing_path': match_path,
                    'similarity': similarity
                }
        
        return None
    
    async def import_file(self, file_path: Path, audible_product: Dict) -> str:
        """
        Import single M4B file with Audible metadata enrichment.
        
        Args:
            file_path: Source file path
            audible_product: Audible product dictionary with metadata
            
        Returns:
            Final file path in library
        """
        file_path = Path(file_path)
        
        if not file_path.exists():
            raise FileNotFoundError(f"Source file not found: {file_path}")
        
        # Extract asin and title
        asin = audible_product.get('asin')
        title = audible_product.get('title', file_path.stem)
        
        logger.info(f"Importing '{title}' (ASIN: {asin})")
        
        # Build target path using naming pattern
        target_path = self.downloader.build_path_from_pattern(
            base_path=str(self.library_path),
            title=title,
            authors=audible_product.get('authors', []),
            narrators=audible_product.get('narrators', []),
            series=audible_product.get('series'),
            release_date=audible_product.get('release_date'),
            publisher=audible_product.get('publisher_name'),
            language=audible_product.get('language'),
            asin=asin
        )
        
        logger.info(f"Target path: {target_path}")
        
        # Create parent directory
        target_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Move file to target location
        logger.info(f"Moving file from {file_path} to {target_path}")
        shutil.move(str(file_path), str(target_path))
        
        # Enrich metadata using Audible data
        try:
            async with audible.AsyncClient(auth=self.auth) as client:
                await self.downloader._add_enhanced_metadata(client, target_path, asin)
                logger.info(f"Metadata enriched for '{title}'")
        except Exception as e:
            logger.warning(f"Could not enrich metadata: {e}")
        
        # Add to library state
        self.downloader.add_to_library(
            asin=asin,
            title=title,
            file_path=str(target_path),
            imported_from=str(file_path)
        )
        
        logger.info(f"Successfully imported '{title}' to {target_path}")
        return str(target_path)
    
    async def batch_import(self, imports: List[Dict]) -> Dict:
        """
        Import multiple files in batch.
        
        Args:
            imports: List of import dictionaries with file_path and audible_product
            
        Returns:
            Statistics dictionary with results
        """
        results = {
            'total': len(imports),
            'successful': 0,
            'failed': 0,
            'errors': []
        }
        
        for import_item in imports:
            file_path = Path(import_item['file_path'])
            audible_product = import_item['audible_product']
            
            try:
                # Update queue state
                self.queue_manager.update_import(
                    str(file_path),
                    {'state': ImportState.IMPORTING.value}
                )
                
                # Import file
                final_path = await self.import_file(file_path, audible_product)
                
                # Update queue state
                self.queue_manager.update_import(
                    str(file_path),
                    {
                        'state': ImportState.COMPLETE.value,
                        'final_path': final_path
                    }
                )
                
                results['successful'] += 1
                
            except Exception as e:
                logger.error(f"Failed to import {file_path}: {e}")
                
                # Update queue state
                self.queue_manager.update_import(
                    str(file_path),
                    {
                        'state': ImportState.ERROR.value,
                        'error': str(e)
                    }
                )
                
                results['failed'] += 1
                results['errors'].append({
                    'file': str(file_path),
                    'error': str(e)
                })
        
        return results

