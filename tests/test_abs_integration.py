"""Mocked ABS wire contract and catalog reconciliation tests."""

from contextlib import contextmanager
import sqlite3

import pytest
import requests

from app.services import audiobookshelf as abs_service
from app.services import library_manager


class Response:
    def __init__(self, body=None, status=200):
        self.body = body
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            error = requests.HTTPError("failed")
            error.response = self
            raise error

    def json(self):
        return self.body


class Session:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return next(self.responses)


def item(item_id, title, *, asin=None, author="Writer", missing=False):
    return {"id": item_id, "mediaType": "book", "isMissing": missing,
            "media": {"metadata": {"title": title, "asin": asin, "authorName": author}}}


def test_scan_and_paginated_items_use_documented_api():
    session = Session([Response({}), Response({"results": [item("a", "One")], "total": 2}),
                       Response({"results": [item("b", "Two")], "total": 2})])
    client = abs_service.AudiobookshelfClient("http://abs:13378", "secret", "lib_1", session=session)
    client.trigger_scan()
    assert len(client.list_items()) == 2
    assert session.calls[0][0:2] == ("POST", "http://abs:13378/api/libraries/lib_1/scan")
    assert session.calls[1][2]["params"]["page"] == 0
    assert session.calls[2][2]["params"]["page"] == 1
    assert all(call[2]["headers"] == {"Authorization": "Bearer secret"} for call in session.calls)


@pytest.fixture
def catalog(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE books (asin TEXT PRIMARY KEY, title TEXT, authors TEXT, status TEXT);
        CREATE TABLE abs_items (asin TEXT PRIMARY KEY, item_id TEXT, match_method TEXT,
                                status TEXT, last_synced REAL);
        INSERT INTO books VALUES ('A1', 'The First Book', 'Writer', 'downloaded');
        INSERT INTO books VALUES ('A2', 'Second: Book', 'Another', 'downloaded');
        INSERT INTO books VALUES ('A3', 'Duplicate Title', 'Writer', 'downloaded');
        INSERT INTO books VALUES ('A4', 'Unindexed', 'Writer', 'downloaded');
        INSERT INTO books VALUES ('A5', 'Wanted', 'Writer', 'wanted');
    """)

    @contextmanager
    def tx():
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    monkeypatch.setattr(abs_service, "get_db", lambda: conn)
    monkeypatch.setattr(abs_service, "transaction", tx)
    yield conn
    conn.close()


def test_reconcile_asin_title_missing_ambiguous_and_pending(catalog):
    counts = abs_service.reconcile_items([
        item("abs-1", "Different title", asin="A1"),
        item("abs-2", "Second Book", asin=None, author="Another", missing=True),
        item("abs-3", "Duplicate Title", asin=None),
        item("abs-4", "Duplicate Title", asin=None),
        item("wrong-asin", "Unindexed", asin="OTHER"),
    ])
    assert counts == {"matched": 1, "missing": 1, "ambiguous": 1, "pending": 1}
    rows = {r["asin"]: dict(r) for r in catalog.execute("SELECT * FROM abs_items")}
    assert (rows["A1"]["item_id"], rows["A1"]["match_method"]) == ("abs-1", "asin")
    assert (rows["A2"]["item_id"], rows["A2"]["match_method"]) == ("abs-2", "title")
    assert rows["A3"]["item_id"] is None
    assert rows["A4"]["item_id"] is None
    assert "A5" not in rows
    assert catalog.execute("SELECT status FROM books WHERE asin='A2'").fetchone()[0] == "downloaded"


def test_abs_absence_or_unsupported_version_keeps_last_good_status(catalog, monkeypatch):
    abs_service.reconcile_items([item("abs-1", "First", asin="A1")])
    prior = dict(catalog.execute("SELECT * FROM abs_items WHERE asin='A1'").fetchone())
    monkeypatch.delenv("ABS_URL", raising=False)
    monkeypatch.delenv("ABS_API_TOKEN", raising=False)
    monkeypatch.delenv("ABS_LIBRARY_ID", raising=False)
    assert abs_service.AudiobookshelfClient.from_environment() is None
    client = abs_service.AudiobookshelfClient(
        "http://abs:13378", "secret", "lib_1",
        session=Session([Response({"items": [], "total": 0})]),
    )
    with pytest.raises(abs_service.AudiobookshelfError, match="Unsupported"):
        abs_service.reconcile_items(client.list_items())
    assert dict(catalog.execute("SELECT * FROM abs_items WHERE asin='A1'").fetchone()) == prior


def test_abs_http_error_does_not_expose_token():
    client = abs_service.AudiobookshelfClient(
        "http://abs:13378", "private-token", "lib_1", session=Session([Response(status=403)]),
    )
    with pytest.raises(abs_service.AudiobookshelfError) as caught:
        client.trigger_scan()
    assert "403" in str(caught.value)
    assert "private-token" not in str(caught.value)


def test_download_scan_failure_is_best_effort(monkeypatch):
    monkeypatch.setenv("ABS_URL", "http://abs:13378")
    monkeypatch.setenv("ABS_API_TOKEN", "secret")
    monkeypatch.setenv("ABS_LIBRARY_ID", "lib_1")
    monkeypatch.setattr(abs_service.AudiobookshelfClient, "trigger_scan",
                        lambda self: (_ for _ in ()).throw(abs_service.AudiobookshelfError("offline")))
    abs_service.trigger_scan_after_download()


def test_completed_download_requests_abs_scan(tmp_path, monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.execute("""CREATE TABLE books (
        asin TEXT PRIMARY KEY, title TEXT, status TEXT, file_path TEXT,
        file_size_bytes INTEGER, last_seen_on_disk REAL, library_name TEXT,
        downloaded_by_account TEXT, added_at REAL, updated_at REAL)""")

    @contextmanager
    def tx():
        yield conn
        conn.commit()

    monkeypatch.setattr(library_manager, "transaction", tx)
    session = Session([Response({})])
    client = abs_service.AudiobookshelfClient("http://abs:13378", "secret", "lib_1", session=session)
    monkeypatch.setattr(abs_service.AudiobookshelfClient, "from_environment", lambda: client)
    book_file = tmp_path / "Owned.m4b"
    book_file.write_bytes(b"test")
    library_manager.LibraryManager(tmp_path, "family").add_to_library("A1", "Owned", str(book_file))
    assert conn.execute("SELECT status FROM books WHERE asin='A1'").fetchone()[0] == "downloaded"
    assert session.calls[0][0] == "POST"
    conn.close()
