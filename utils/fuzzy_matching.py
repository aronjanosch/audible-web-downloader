"""
Shared fuzzy text matching utilities for duplicate detection.
Used by downloader, library scanner, and importer modules.
"""
import unicodedata
import re


def normalize_for_matching(text: str) -> str:
    """
    Normalize text for fuzzy matching (used for duplicate detection).

    Args:
        text: Text to normalize

    Returns:
        Normalized text with lowercasing, diacritic removal, and punctuation cleanup
    """
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


def calculate_similarity(text1: str, text2: str) -> float:
    """
    Calculate word-based similarity between two texts (Jaccard similarity).

    Args:
        text1: First text to compare
        text2: Second text to compare

    Returns:
        Similarity score from 0.0 to 1.0, with bonuses for substring and number matching
    """
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
