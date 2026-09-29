"""Regression checks for Audible/local library matching."""
from library_scanner import LibraryComparator


def test_matching_title_and_author():
    comparator = LibraryComparator()
    result = comparator.compare_libraries(
        [{'title': 'Ex Vitro: c23, 1', 'authors': 'Ralph Edenhofer', 'asin': 'TEST123'}],
        [{'title': 'Ex Vitro: c23, 1', 'authors': 'Ralph Edenhofer', 'file_path': '/library/book.m4b'}],
    )
    assert result['available_count'] == 1
    assert result['missing_count'] == 0


def test_different_author_is_not_matched():
    comparator = LibraryComparator()
    result = comparator.compare_libraries(
        [{'title': 'Shared Title', 'authors': 'Alice'}],
        [{'title': 'Shared Title', 'authors': 'Bob'}],
    )
    assert result['missing_count'] == 1
