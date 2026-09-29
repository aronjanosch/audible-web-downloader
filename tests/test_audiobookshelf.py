"""Regression checks for the configured Audiobookshelf style path builder."""
from app.services import PathBuilder


def test_conditional_path_components():
    path = PathBuilder().build_path_from_pattern(
        '/library', title='Wizards First Rule',
        authors=[{'name': 'Terry Goodkind'}],
        narrators=[{'name': 'Sam Tsoutsouvas'}],
        series=[{'title': 'Sword of Truth', 'sequence': '1'}],
        release_date='1994-08-15',
    )
    assert path.name == 'Wizards First Rule.m4b'
    assert 'Terry Goodkind' in path.parts
    assert 'Sword of Truth' in path.parts
    assert any('Vol. 1 - 1994 - Wizards First Rule' in part for part in path.parts)


def test_empty_optional_metadata_has_clean_path():
    path = PathBuilder().build_path_from_pattern(
        '/library', title='Minimal Book', authors=[{'name': 'Author'}],
        narrators=None, series=None, release_date=None,
    )
    assert path.name == 'Minimal Book.m4b'
    assert 'Author' in path.parts
    assert all('Vol.' not in part for part in path.parts)
