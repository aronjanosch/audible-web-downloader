"""
Local audiobook library scanner and comparison module.

Scans local directory structure (Author > Series > M4B files) and provides
comparison functionality with Audible library to identify missing books.
"""

import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
import unicodedata
from mutagen.mp4 import MP4
from mutagen.id3 import ID3NoHeaderError
import logging

logger = logging.getLogger(__name__)

class LocalLibraryScanner:
    """Scans and manages local audiobook library."""
    
    def __init__(self, library_path: str):
        """Initialize scanner with library path."""
        self.library_path = Path(library_path)
        self.supported_extensions = {'.m4b', '.m4a', '.mp3', '.aax'}
        
    def scan_library(self) -> List[Dict]:
        """
        Scan local library directory structure.
        Expected structure: Author/Series/Book.m4b or Author/Book.m4b
        
        Returns:
            List of book dictionaries with metadata
        """
        books = []
        
        if not self.library_path.exists():
            logger.warning(f"Library path does not exist: {self.library_path}")
            return books
            
        # Scan author directories
        for author_dir in self.library_path.iterdir():
            if not author_dir.is_dir() or author_dir.name.startswith('.'):
                continue
                
            books.extend(self._scan_author_directory(author_dir))
            
        logger.info(f"Scanned {len(books)} books from local library")
        return books
    
    def _scan_author_directory(self, author_dir: Path) -> List[Dict]:
        """Scan an author's directory for books and series."""
        books = []
        author_name = author_dir.name
        
        for item in author_dir.iterdir():
            if item.is_file() and item.suffix.lower() in self.supported_extensions:
                # Book directly in author directory
                book_data = self._extract_book_metadata(item, author_name, None)
                if book_data:
                    books.append(book_data)
                    
            elif item.is_dir() and not item.name.startswith('.'):
                # Series or sub-directory
                series_name = item.name
                for book_file in item.iterdir():
                    if book_file.is_file() and book_file.suffix.lower() in self.supported_extensions:
                        book_data = self._extract_book_metadata(book_file, author_name, series_name)
                        if book_data:
                            books.append(book_data)
        
        return books
    
    def _extract_book_metadata(self, file_path: Path, author_name: str, series_name: Optional[str]) -> Optional[Dict]:
        """Extract metadata from audiobook file."""
        try:
            # Try to get metadata from file
            metadata = self._get_file_metadata(file_path)
            
            # Extract title from filename if not in metadata
            title = metadata.get('title') or self._extract_title_from_filename(file_path.stem)
            
            # Detect language from filename or path
            language = self._detect_language(file_path)
            
            book_data = {
                'title': title,
                'authors': metadata.get('author') or author_name,
                'series': series_name,
                'file_path': str(file_path),
                'file_size': file_path.stat().st_size,
                'language': language,
                'duration_seconds': metadata.get('duration', 0),
                'isbn': metadata.get('isbn'),
                'asin': metadata.get('asin'),
                'normalized_title': self._normalize_title(title),
                'normalized_author': self._normalize_title(metadata.get('author') or author_name)
            }
            
            return book_data
            
        except Exception as e:
            logger.warning(f"Failed to extract metadata from {file_path}: {e}")
            return None
    
    def _get_file_metadata(self, file_path: Path) -> Dict:
        """Extract metadata from audio file using mutagen."""
        metadata = {}
        
        try:
            if file_path.suffix.lower() in {'.m4b', '.m4a'}:
                audio_file = MP4(str(file_path))
                metadata = {
                    'title': self._get_mp4_tag(audio_file, '©nam'),
                    'author': self._get_mp4_tag(audio_file, '©ART') or self._get_mp4_tag(audio_file, 'aART'),
                    'album': self._get_mp4_tag(audio_file, '©alb'),
                    'duration': getattr(audio_file.info, 'length', 0),
                    'isbn': self._get_mp4_tag(audio_file, '----:com.apple.iTunes:ISBN'),
                    'asin': self._get_mp4_tag(audio_file, '----:com.apple.iTunes:ASIN')
                }
            # Add MP3 support if needed
            
        except Exception as e:
            logger.debug(f"Could not read metadata from {file_path}: {e}")
            
        return {k: v for k, v in metadata.items() if v}
    
    def _get_mp4_tag(self, audio_file, tag_name: str) -> Optional[str]:
        """Get MP4 tag value safely."""
        try:
            tag_value = audio_file.get(tag_name)
            if tag_value:
                if isinstance(tag_value[0], bytes):
                    return tag_value[0].decode('utf-8')
                return str(tag_value[0])
        except (IndexError, AttributeError, UnicodeDecodeError):
            pass
        return None
    
    def _extract_title_from_filename(self, filename: str) -> str:
        """Extract clean title from filename."""
        # Remove common patterns like "Book 1 - ", "01 - ", etc.
        title = re.sub(r'^(Book\s+\d+\s*-\s*|Buch\s+\d+\s*-\s*|\d+\s*-\s*)', '', filename, flags=re.IGNORECASE)
        
        # Remove file extension artifacts
        title = re.sub(r'\s*\([^)]*\)$', '', title)  # Remove trailing parentheses
        
        return title.strip()
    
    def _detect_language(self, file_path: Path) -> str:
        """Detect language from file path or name."""
        path_str = str(file_path).lower()
        
        # Language indicators in path
        if any(x in path_str for x in ['deutsch', 'german', '_de', ' de ', 'german']):
            return 'de'
        elif any(x in path_str for x in ['english', '_en', ' en ', 'eng']):
            return 'en'
        elif any(x in path_str for x in ['français', 'french', '_fr', ' fr ']):
            return 'fr'
        elif any(x in path_str for x in ['español', 'spanish', '_es', ' es ']):
            return 'es'
            
        # Default to unknown
        return 'unknown'
    
    def _normalize_title(self, title: str) -> str:
        """Normalize title for comparison."""
        if not title:
            return ""
            
        # Remove diacritics and convert to lowercase
        normalized = unicodedata.normalize('NFD', title.lower())
        normalized = ''.join(c for c in normalized if unicodedata.category(c) != 'Mn')
        
        # Remove common words and punctuation
        normalized = re.sub(r'\b(the|a|an|der|die|das|le|la|el|un|une)\b', '', normalized)
        normalized = re.sub(r'[^\w\s]', '', normalized)
        normalized = re.sub(r'\s+', ' ', normalized).strip()
        
        return normalized

class LibraryComparator:
    """Compares Audible and local libraries to find missing books."""
    
    def __init__(self):
        self.match_threshold = 0.8  # Similarity threshold for fuzzy matching
    
    def compare_libraries(self, audible_books: List[Dict], local_books: List[Dict]) -> Dict:
        """
        Compare Audible and local libraries to find missing books.
        
        Args:
            audible_books: List of books from Audible library
            local_books: List of books from local library
            
        Returns:
            Dict with comparison results
        """
        # Create lookup sets for fast matching
        local_lookup = self._create_lookup_set(local_books)
        
        missing_books = []
        available_books = []
        
        for audible_book in audible_books:
            if self._is_book_available_locally(audible_book, local_lookup, local_books):
                available_books.append(audible_book)
            else:
                missing_books.append(audible_book)
        
        # Find local books not in Audible (extras)
        audible_lookup = self._create_lookup_set(audible_books)
        local_only = [
            book for book in local_books 
            if not self._is_book_available_locally(book, audible_lookup, audible_books)
        ]
        
        return {
            'total_audible': len(audible_books),
            'total_local': len(local_books),
            'missing_from_local': missing_books,
            'available_locally': available_books,
            'local_only': local_only,
            'missing_count': len(missing_books),
            'available_count': len(available_books),
            'local_only_count': len(local_only)
        }
    
    def _create_lookup_set(self, books: List[Dict]) -> Set[str]:
        """Create normalized title+author lookup set."""
        lookup = set()
        for book in books:
            normalized_title = book.get('normalized_title') or self._normalize_for_lookup(book.get('title', ''))
            normalized_author = book.get('normalized_author') or self._normalize_for_lookup(book.get('authors', ''))
            lookup.add(f"{normalized_title}|{normalized_author}")
        return lookup
    
    def _is_book_available_locally(self, audible_book: Dict, local_lookup: Set[str], local_books: List[Dict]) -> bool:
        """Check if an Audible book is available in local library."""
        audible_title = self._normalize_for_lookup(audible_book.get('title', ''))
        audible_author = self._normalize_for_lookup(audible_book.get('authors', ''))
        
        # Direct lookup first
        lookup_key = f"{audible_title}|{audible_author}"
        if lookup_key in local_lookup:
            return True
        
        # Fuzzy matching for different editions/formats
        return self._fuzzy_match_book(audible_book, local_books)
    
    def _fuzzy_match_book(self, audible_book: Dict, local_books: List[Dict]) -> bool:
        """Perform fuzzy matching to find similar books."""
        audible_title = audible_book.get('title', '').lower()
        audible_author = audible_book.get('authors', '').lower()
        
        for local_book in local_books:
            local_title = local_book.get('title', '').lower()
            local_author = local_book.get('authors', '').lower()
            
            # Calculate similarity (simple word overlap method)
            title_similarity = self._calculate_word_similarity(audible_title, local_title)
            author_similarity = self._calculate_word_similarity(audible_author, local_author)
            
            # Consider it a match if both title and author are similar enough
            if title_similarity >= self.match_threshold and author_similarity >= 0.6:
                return True
                
        return False
    
    def _calculate_word_similarity(self, text1: str, text2: str) -> float:
        """Calculate word-based similarity between two texts."""
        if not text1 or not text2:
            return 0.0
            
        words1 = set(text1.split())
        words2 = set(text2.split())
        
        if not words1 or not words2:
            return 0.0
            
        intersection = len(words1.intersection(words2))
        union = len(words1.union(words2))
        
        return intersection / union if union > 0 else 0.0
    
    def _normalize_for_lookup(self, text: str) -> str:
        """Normalize text for lookup comparison."""
        if not text:
            return ""
            
        # Simple normalization
        normalized = unicodedata.normalize('NFD', text.lower())
        normalized = ''.join(c for c in normalized if unicodedata.category(c) != 'Mn')
        normalized = re.sub(r'[^\w\s]', '', normalized)
        normalized = re.sub(r'\s+', ' ', normalized).strip()
        
        return normalized