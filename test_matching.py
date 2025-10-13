#!/usr/bin/env python3
"""
Test script to debug book matching logic
"""

from library_scanner import LibraryComparator

def test_matching():
    comparator = LibraryComparator()
    
    # Test case from your example
    audible_title = "ex vitro - c23 - Band 1"  # What might come from Audible
    local_title = "Ex Vitro: c23, 1"  # From your M4B metadata
    
    author = "Ralph Edenhofer"
    
    # Test normalization
    norm_audible = comparator._normalize_for_matching(audible_title)
    norm_local = comparator._normalize_for_matching(local_title)
    
    print("=== Normalization Test ===")
    print(f"Audible title: '{audible_title}' -> '{norm_audible}'")
    print(f"Local title:   '{local_title}' -> '{norm_local}'")
    print()
    
    # Test similarity
    title_sim = comparator._calculate_advanced_similarity(norm_audible, norm_local)
    author_sim = comparator._calculate_word_similarity(author.lower(), author.lower())
    
    print("=== Similarity Test ===")
    print(f"Title similarity: {title_sim:.3f} (threshold: {comparator.match_threshold})")
    print(f"Author similarity: {author_sim:.3f}")
    print(f"Would match: {title_sim >= comparator.match_threshold and author_sim >= 0.7}")
    print()
    
    # Test with books
    audible_book = {
        'title': audible_title,
        'authors': author,
        'asin': 'TEST123'
    }
    
    local_books = [{
        'title': local_title,
        'authors': author,
        'file_path': '/path/to/file.m4b'
    }]
    
    match_result = comparator._fuzzy_match_book(audible_book, local_books)
    print(f"=== Full Match Test ===")
    print(f"Match result: {match_result}")

if __name__ == "__main__":
    test_matching()