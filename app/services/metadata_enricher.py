"""
MetadataEnricher service for handling audiobook metadata operations.

This service is responsible for:
- Extracting ASIN from M4B file metadata
- Fetching enhanced book metadata from Audible API
- Embedding metadata into M4B files (title, authors, narrators, etc.)
- Exporting content metadata to JSON files
"""

import json
import re
from pathlib import Path
from typing import Optional, Dict
from mutagen.mp4 import MP4
import audible


class MetadataEnricher:
    """
    Handles metadata extraction, enrichment, and embedding for audiobook files.
    """

    @staticmethod
    def extract_asin_from_m4b(file_path: Path) -> Optional[str]:
        """
        Extract ASIN from M4B file metadata.
        ASIN is stored in ©cmt tag as "ASIN: {asin}"

        Args:
            file_path: Path to M4B file

        Returns:
            ASIN string if found, None otherwise
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

        except Exception:
            pass

        return None

    @staticmethod
    async def export_content_metadata(
        client: audible.AsyncClient,
        asin: str,
        output_dir: Path,
        license_response: Dict
    ) -> None:
        """
        Export content metadata from license response to JSON file.

        Args:
            client: Audible async client
            asin: Amazon Standard Identification Number
            output_dir: Directory to save metadata file
            license_response: License response from Audible API
        """
        try:
            content_metadata = license_response.get("content_license", {}).get("content_metadata", {})
            metadata_file = output_dir / f"content_metadata_{asin}.json"
            metadata_file.write_text(json.dumps(content_metadata, indent=2))
        except Exception as e:
            print(f"⚠️  Could not export content metadata: {e}")

    @staticmethod
    async def add_enhanced_metadata(
        client: audible.AsyncClient,
        m4b_file: Path,
        asin: str
    ) -> None:
        """
        Fetch book details from Audible API and embed enhanced metadata into M4B file.

        Embeds:
        - Title and subtitle
        - Authors
        - Narrators
        - Publisher
        - Release date and year
        - Description
        - Series information
        - Language
        - ISBN
        - ASIN

        Args:
            client: Audible async client
            m4b_file: Path to M4B file
            asin: Amazon Standard Identification Number
        """
        try:
            book_details = await client.get(
                f"catalog/products/{asin}",
                params={"response_groups": "product_attrs,product_desc,contributors,media,series"}
            )
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
            print(f"✓ Metadata added successfully")
        except Exception as e:
            print(f"⚠️  Could not add enhanced metadata: {e}")
