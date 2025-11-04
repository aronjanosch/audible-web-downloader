"""
PathBuilder service for handling audiobook file paths and naming patterns.

This service is responsible for:
- Building file paths based on naming patterns
- Formatting author, narrator, and series information
- Sanitizing filenames for cross-platform compatibility
- Processing conditional bracket syntax in patterns
"""

import re
from pathlib import Path
from typing import Optional, List, Dict, Tuple
from settings import get_naming_pattern


class PathBuilder:
    """
    Handles audiobook file path construction and naming pattern logic.
    """

    @staticmethod
    def sanitize_filename(filename: str) -> str:
        """
        Sanitize filename by removing invalid characters.

        Args:
            filename: Raw filename string

        Returns:
            Sanitized filename safe for file systems
        """
        return re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f-\x9f]', '_', filename)[:200]

    @staticmethod
    def format_author(authors) -> str:
        """
        Format author name(s) from various input formats, excluding translators.

        Translators are identified by:
        1. Explicit markers like "- Übersetzer", "- Translator"
        2. Having no ASIN when other authors have ASINs (likely translator/contributor)

        Args:
            authors: String, list of strings, or list of dicts with 'name' and 'asin'

        Returns:
            Formatted author string
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

    @staticmethod
    def format_narrator(narrators) -> str:
        """
        Format narrator name(s) from various input formats.

        Args:
            narrators: String, list of strings, or list of dicts with 'name'

        Returns:
            Formatted narrator string (empty string if no narrators)
        """
        if isinstance(narrators, str):
            return narrators if narrators else ""
        elif isinstance(narrators, list) and narrators:
            narrator_names = [n.get('name', '') if isinstance(n, dict) else str(n) for n in narrators[:2]]
            narrator_names = [name for name in narrator_names if name]
            if narrator_names:
                return " & ".join(narrator_names)
        return ""

    @staticmethod
    def format_series(series) -> Tuple[Optional[str], Optional[str]]:
        """
        Format series information.

        Args:
            series: String, or list of dicts with 'title' and 'sequence'

        Returns:
            Tuple of (series_name, volume_number)
        """
        if isinstance(series, str) and series:
            return series, None
        elif isinstance(series, list) and series:
            series_name = series[0].get('title', '') if series[0].get('title') else None
            volume = series[0].get('sequence', None)
            return series_name, volume
        return None, None

    def process_conditional_brackets(self, pattern: str, replacements: Dict[str, str]) -> str:
        """
        Process conditional bracket syntax [text {Placeholder}].
        If any placeholder inside brackets is empty, the entire bracketed section is removed.

        Args:
            pattern: Naming pattern with conditional brackets
            replacements: Dictionary of placeholder values

        Returns:
            Pattern with conditional sections resolved
        """
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

    @staticmethod
    def cleanup_pattern(text: str) -> str:
        """
        Clean up the pattern by removing extra spaces, dashes, and empty brackets.

        Args:
            text: Text to clean up

        Returns:
            Cleaned text
        """
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
        author_str = self.format_author(authors)
        narrator_str = self.format_narrator(narrators)
        series_name, volume = self.format_series(series)

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
        path_str = self.process_conditional_brackets(pattern, replacements)

        # Replace placeholders in pattern
        for placeholder, value in replacements.items():
            path_str = path_str.replace(placeholder, value)

        # Clean up path: remove empty segments and consecutive slashes
        path_parts = []
        for part in path_str.split('/'):
            part = part.strip()
            if part:  # Skip empty segments (happens when optional placeholders are empty)
                # Apply cleanup to remove extra spaces, dashes, and empty brackets
                part = self.cleanup_pattern(part)
                if part:  # Check again after cleanup
                    # Sanitize each path component
                    sanitized = self.sanitize_filename(part)
                    if sanitized and sanitized != ".m4b":  # Don't add segments that are just the extension
                        path_parts.append(sanitized)

        # Build final path directly from pattern (pattern is the source of truth)
        if not path_parts:
            # Fallback to flat structure if pattern results in empty path
            safe_title = self.sanitize_filename(title)
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

        NOTE: This is legacy code. Consider using build_path_from_pattern instead.

        Returns:
            Path object with structure: base_path/Author/[Series]/Title/
        """
        if not use_audiobookshelf_structure:
            # Legacy flat structure
            return Path(base_path) / self.sanitize_filename(title)

        # 1. Build Author Folder
        author_folder = self.format_author(authors) if authors else "Unknown Author"
        author_folder = self.sanitize_filename(author_folder)

        # 2. Build Series Folder (Optional)
        series_folder = None
        series_sequence = None

        if isinstance(series, str):
            # Series is a string from library fetch
            if series:
                series_folder = self.sanitize_filename(series)
        elif isinstance(series, list) and series:
            # Series is a list from API
            if series[0].get('title'):
                series_folder = self.sanitize_filename(series[0]['title'])
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
        narrator_str = self.format_narrator(narrators) if narrators else None

        if narrator_str:
            title_folder = " - ".join(title_parts) + f" {{{narrator_str}}}"
        else:
            title_folder = " - ".join(title_parts)

        title_folder = self.sanitize_filename(title_folder)

        # 4. Construct Path
        if series_folder:
            return Path(base_path) / author_folder / series_folder / title_folder
        else:
            return Path(base_path) / author_folder / title_folder

    def get_file_paths(
        self,
        downloads_dir: Path,
        library_path: Path,
        book_title: str,
        asin: str,
        product: Optional[Dict] = None
    ) -> Dict[str, Path]:
        """
        Build file paths for temporary downloads and final library location.

        Temp files (AAX, vouchers, metadata) go to downloads_dir.
        Final M4B file goes to library_path following naming pattern.

        Args:
            downloads_dir: Temporary download directory
            library_path: Final library path
            book_title: Title of the book
            asin: Amazon Standard Identification Number
            product: Optional product metadata for path building

        Returns:
            Dictionary of file paths for various stages of processing
        """
        # 1. Create temporary download directory (simple sanitized title)
        safe_title = self.sanitize_filename(book_title)
        temp_dir = downloads_dir / safe_title
        temp_dir.mkdir(parents=True, exist_ok=True)

        # 2. Build final library path using naming pattern
        if product:
            try:
                # Use the new pattern-based path builder for final library location
                series_info = product.get('series_data') or product.get('series')

                final_m4b_path = self.build_path_from_pattern(
                    base_path=str(library_path),
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
                final_m4b_path = library_path / safe_title / f"{safe_title}.m4b"
        else:
            # No product metadata, use flat structure in library
            final_m4b_path = library_path / safe_title / f"{safe_title}.m4b"

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
