#!/usr/bin/env python3
"""
Test script for AudioBookshelf naming structure implementation.
Tests the build_audiobookshelf_path function with various metadata scenarios.
"""

from pathlib import Path
from downloader import AudiobookDownloader

def test_conditional_patterns():
    """Test the conditional bracket syntax and cleanup functionality."""

    # Create a mock downloader with necessary methods
    class MockDownloader:
        def __init__(self):
            pass

        def _sanitize_filename(self, filename):
            import re
            return re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f-\x9f]', '_', filename)[:200]

        # Copy methods from AudiobookDownloader
        _format_author = AudiobookDownloader._format_author
        _format_narrator = AudiobookDownloader._format_narrator
        _format_series = AudiobookDownloader._format_series
        _process_conditional_brackets = AudiobookDownloader._process_conditional_brackets
        _cleanup_pattern = AudiobookDownloader._cleanup_pattern
        build_path_from_pattern = AudiobookDownloader.build_path_from_pattern

    downloader = MockDownloader()
    base_path = "/library"

    print("Testing Conditional Pattern Syntax")
    print("=" * 80)

    # Test 1: Series book with volume - all conditionals included
    print("\n1. Series Book with Volume (all conditionals included):")
    result = downloader.build_path_from_pattern(
        base_path,
        title='Wizards First Rule',
        authors=[{'name': 'Terry Goodkind'}],
        narrators=[{'name': 'Sam Tsoutsouvas'}],
        series=[{'title': 'Sword of Truth', 'sequence': '1'}],
        release_date='1994-08-15'
    )
    print(f"Result: {result}")
    print(f"Expected: /library/Terry Goodkind/Sword of Truth/Vol. 1 - 1994 - Wizards First Rule {{Sam Tsoutsouvas}}.m4b")

    # Test 2: Standalone book - series and volume conditionals omitted
    print("\n2. Standalone Book (no series/volume - conditionals omitted):")
    result = downloader.build_path_from_pattern(
        base_path,
        title='Hackers',
        authors=[{'name': 'Steven Levy'}],
        narrators=[{'name': 'Mike Chamberlain'}],
        series=[],
        release_date='2010-05-19'
    )
    print(f"Result: {result}")
    print(f"Expected: /library/Steven Levy/2010 - Hackers {{Mike Chamberlain}}.m4b")

    # Test 3: Book without narrator - narrator conditional omitted
    print("\n3. Book Without Narrator (narrator conditional omitted):")
    result = downloader.build_path_from_pattern(
        base_path,
        title='Some Book',
        authors=[{'name': 'Author Name'}],
        narrators=None,
        series=[{'title': 'Series Name', 'sequence': '2'}],
        release_date='2020-01-01'
    )
    print(f"Result: {result}")
    print(f"Expected: /library/Author Name/Series Name/Vol. 2 - 2020 - Some Book.m4b")

    # Test 4: Series without volume number
    print("\n4. Series Without Volume Number (volume conditional omitted):")
    result = downloader.build_path_from_pattern(
        base_path,
        title='Book Title',
        authors=[{'name': 'Author Name'}],
        narrators=[{'name': 'Narrator Name'}],
        series=[{'title': 'Series Name', 'sequence': None}],
        release_date='2021-03-15'
    )
    print(f"Result: {result}")
    print(f"Expected: /library/Author Name/Series Name/2021 - Book Title {{Narrator Name}}.m4b")

    # Test 5: Minimal metadata - multiple conditionals omitted
    print("\n5. Minimal Metadata (multiple conditionals omitted):")
    result = downloader.build_path_from_pattern(
        base_path,
        title='Minimal Book',
        authors=[{'name': 'Author'}],
        narrators=None,
        series=None,
        release_date='2022-01-01'
    )
    print(f"Result: {result}")
    print(f"Expected: /library/Author/2022 - Minimal Book.m4b")

    # Test 6: Multiple authors with series
    print("\n6. Multiple Authors with Series:")
    result = downloader.build_path_from_pattern(
        base_path,
        title='The Courage to Be Disliked',
        authors=[{'name': 'Ichiro Kishimi'}, {'name': 'Fumitake Koga'}],
        narrators=[{'name': 'Narrator One'}],
        series=[{'title': 'Philosophy Series', 'sequence': '1'}],
        release_date='2018-05-08'
    )
    print(f"Result: {result}")
    print(f"Expected: /library/Ichiro Kishimi & Fumitake Koga/Philosophy Series/Vol. 1 - 2018 - The Courage to Be Disliked {{Narrator One}}.m4b")

    # Test 7: Test cleanup - extra spaces and dashes
    print("\n7. Cleanup Test (testing internal cleanup function):")
    test_strings = [
        ("Vol.  - 2024 - Title", "Vol. - 2024 - Title"),
        ("Title  -  - Author", "Title - Author"),
        (" - Leading dash", "Leading dash"),
        ("Trailing dash - ", "Trailing dash"),
        ("Title ()", "Title"),
        ("Title []", "Title"),
        ("Title {}", "Title"),
        ("Multiple    spaces", "Multiple spaces"),
    ]
    for input_str, expected in test_strings:
        result = downloader._cleanup_pattern(input_str)
        match = "✓" if result == expected else "✗"
        print(f"  {match} '{input_str}' → '{result}' (expected: '{expected}')")

    # Test 8: Edge case - no year
    print("\n8. No Release Date:")
    result = downloader.build_path_from_pattern(
        base_path,
        title='Unknown Date Book',
        authors=[{'name': 'Author Name'}],
        narrators=None,
        series=None,
        release_date=None
    )
    print(f"Result: {result}")
    print(f"Expected: /library/Author Name/Unknown Date Book.m4b (with year omitted)")

    print("\n" + "=" * 80)
    print("Conditional pattern tests completed!")

def test_path_builder():
    """Test the AudioBookshelf path builder with various scenarios."""

    # Create a mock downloader (without authentication)
    class MockDownloader:
        def __init__(self):
            pass

        def _sanitize_filename(self, filename):
            import re
            return re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f-\x9f]', '_', filename)[:200]

        # Copy the build_audiobookshelf_path method from AudiobookDownloader
        build_audiobookshelf_path = AudiobookDownloader.build_audiobookshelf_path

    downloader = MockDownloader()
    base_path = "/library"

    print("Testing AudioBookshelf Path Builder")
    print("=" * 80)

    # Test 1: Series book with full metadata
    print("\n1. Series Book with Full Metadata:")
    test_data = {
        'title': 'Wizards First Rule',
        'authors': [{'name': 'Terry Goodkind'}],
        'narrators': [{'name': 'Sam Tsoutsouvas'}],
        'series': [{'title': 'Sword of Truth', 'sequence': '1'}],
        'release_date': '1994-08-15'
    }
    result = downloader.build_audiobookshelf_path(
        base_path,
        test_data['title'],
        test_data['authors'],
        test_data['narrators'],
        test_data['series'],
        test_data['release_date'],
        use_audiobookshelf_structure=True
    )
    print(f"Input: {test_data}")
    print(f"Output: {result}")
    print(f"Expected: /library/Terry Goodkind/Sword of Truth/Vol. 1 - 1994 - Wizards First Rule {{Sam Tsoutsouvas}}")

    # Test 2: Standalone book
    print("\n2. Standalone Book:")
    test_data = {
        'title': 'Hackers',
        'authors': [{'name': 'Steven Levy'}],
        'narrators': [{'name': 'Mike Chamberlain'}],
        'series': [],
        'release_date': '2010-05-19'
    }
    result = downloader.build_audiobookshelf_path(
        base_path,
        test_data['title'],
        test_data['authors'],
        test_data['narrators'],
        test_data['series'],
        test_data['release_date'],
        use_audiobookshelf_structure=True
    )
    print(f"Input: {test_data}")
    print(f"Output: {result}")
    print(f"Expected: /library/Steven Levy/2010 - Hackers {{Mike Chamberlain}}")

    # Test 3: Multiple authors
    print("\n3. Multiple Authors:")
    test_data = {
        'title': 'The Courage to Be Disliked',
        'authors': [{'name': 'Ichiro Kishimi'}, {'name': 'Fumitake Koga'}],
        'narrators': [{'name': 'Narrator One'}],
        'release_date': '2018-05-08'
    }
    result = downloader.build_audiobookshelf_path(
        base_path,
        test_data['title'],
        test_data['authors'],
        test_data['narrators'],
        None,
        test_data['release_date'],
        use_audiobookshelf_structure=True
    )
    print(f"Input: {test_data}")
    print(f"Output: {result}")
    print(f"Expected: /library/Ichiro Kishimi & Fumitake Koga/2018 - The Courage to Be Disliked {{Narrator One}}")

    # Test 4: Missing metadata
    print("\n4. Missing Metadata:")
    test_data = {
        'title': 'Unknown Book',
        'authors': [],
        'narrators': [],
        'series': [],
        'release_date': None
    }
    result = downloader.build_audiobookshelf_path(
        base_path,
        test_data['title'],
        test_data['authors'],
        test_data['narrators'],
        test_data['series'],
        test_data['release_date'],
        use_audiobookshelf_structure=True
    )
    print(f"Input: {test_data}")
    print(f"Output: {result}")
    print(f"Expected: /library/Unknown Author/Unknown Book")

    # Test 5: Series without sequence
    print("\n5. Series Without Sequence:")
    test_data = {
        'title': 'Book Title',
        'authors': [{'name': 'Author Name'}],
        'series': [{'title': 'Series Name', 'sequence': None}],
        'release_date': '2020-01-01'
    }
    result = downloader.build_audiobookshelf_path(
        base_path,
        test_data['title'],
        test_data['authors'],
        None,
        test_data['series'],
        test_data['release_date'],
        use_audiobookshelf_structure=True
    )
    print(f"Input: {test_data}")
    print(f"Output: {result}")
    print(f"Expected: /library/Author Name/Series Name/2020 - Book Title")

    # Test 6: Special characters in names
    print("\n6. Special Characters in Names:")
    test_data = {
        'title': 'Book: A Tale of Something/Anything',
        'authors': [{'name': 'Author "Nickname" Name'}],
        'release_date': '2021-06-15'
    }
    result = downloader.build_audiobookshelf_path(
        base_path,
        test_data['title'],
        test_data['authors'],
        None,
        None,
        test_data['release_date'],
        use_audiobookshelf_structure=True
    )
    print(f"Input: {test_data}")
    print(f"Output: {result}")
    print(f"Expected: /library/Author _Nickname_ Name/2021 - Book_ A Tale of Something_Anything")

    # Test 7: Legacy flat structure (when disabled)
    print("\n7. Legacy Flat Structure (AudioBookshelf disabled):")
    test_data = {
        'title': 'Simple Book Title',
        'authors': [{'name': 'Author Name'}],
    }
    result = downloader.build_audiobookshelf_path(
        base_path,
        test_data['title'],
        test_data['authors'],
        None,
        None,
        None,
        use_audiobookshelf_structure=False
    )
    print(f"Input: {test_data}")
    print(f"Output: {result}")
    print(f"Expected: /library/Simple Book Title")

    # Test 8: String format from library fetch (real-world scenario)
    print("\n8. String Format from Library Fetch:")
    test_data = {
        'title': 'The Fellowship of the Ring',
        'authors': 'J.R.R. Tolkien',  # String instead of list
        'narrators': 'Rob Inglis',  # String instead of list
        'series': 'The Lord of the Rings',  # String instead of list
        'release_date': '2001-09-05'
    }
    result = downloader.build_audiobookshelf_path(
        base_path,
        test_data['title'],
        test_data['authors'],
        test_data['narrators'],
        test_data['series'],
        test_data['release_date'],
        use_audiobookshelf_structure=True
    )
    print(f"Input: {test_data}")
    print(f"Output: {result}")
    print(f"Expected: /library/J.R.R. Tolkien/The Lord of the Rings/2001 - The Fellowship of the Ring {{Rob Inglis}}")

    print("\n" + "=" * 80)
    print("All tests completed!")


def test_title_parser():
    """Test the AudioBookshelf title parser."""
    from library_scanner import LocalLibraryScanner

    scanner = LocalLibraryScanner("/tmp")

    print("\n\nTesting AudioBookshelf Title Parser")
    print("=" * 80)

    test_cases = [
        ("Wizards First Rule", {'title': 'Wizards First Rule'}),
        ("1994 - Wizards First Rule", {'title': 'Wizards First Rule', 'year': '1994'}),
        ("Vol. 1 - 1994 - Wizards First Rule {Sam Tsoutsouvas}",
         {'title': 'Wizards First Rule', 'sequence': '1', 'year': '1994', 'narrator': 'Sam Tsoutsouvas'}),
        ("Book 2 - 1995 - Stone of Tears {Sam Tsoutsouvas}",
         {'title': 'Stone of Tears', 'sequence': '2', 'year': '1995', 'narrator': 'Sam Tsoutsouvas'}),
        ("2010 - Hackers {Mike Chamberlain}",
         {'title': 'Hackers', 'year': '2010', 'narrator': 'Mike Chamberlain'}),
        ("Vol. 1.5 - 2000 - Intermediate Book",
         {'title': 'Intermediate Book', 'sequence': '1.5', 'year': '2000'}),
    ]

    for i, (input_str, expected) in enumerate(test_cases, 1):
        result = scanner._parse_audiobookshelf_title(input_str)
        print(f"\nTest {i}:")
        print(f"  Input: {input_str}")
        print(f"  Result: {result}")
        print(f"  Expected: {expected}")
        print(f"  Match: {'✓' if result == expected else '✗'}")

    print("\n" + "=" * 80)


if __name__ == "__main__":
    try:
        test_conditional_patterns()
        print("\n\n")
        test_path_builder()
        test_title_parser()
    except Exception as e:
        print(f"\nError during testing: {e}")
        import traceback
        traceback.print_exc()
