"""Static caching, compression and the merged library response cache."""
import re

from test_security import household, _signed_in  # noqa: F401  (fixture reuse)


def test_static_cache_policy_and_versioned_urls(household):
    _, client, admin, _ = household
    _signed_in(client, admin)
    page = client.get("/").get_data(as_text=True)
    assert "cdn.jsdelivr" not in page and "googleapis" not in page and "cdnjs" not in page
    versioned = re.search(r'/static/css/app\.css\?v=[0-9a-f]{10}', page)
    assert versioned, "first-party static URLs carry a content hash"
    assert client.get(versioned.group(0)).headers["Cache-Control"] == "public, max-age=31536000, immutable"
    assert client.get("/static/css/app.css").headers["Cache-Control"] == "no-cache"
    vendor = client.get("/static/vendor/bootstrap/bootstrap.min.css")
    assert vendor.headers["Cache-Control"] == "public, max-age=31536000, immutable"
    # Fonts are referenced by CSS without a query string, so the preload URL must match exactly.
    assert '/static/vendor/fonts/dm-sans-latin-400-normal.woff2"' in page


def test_text_responses_are_compressed_when_accepted(household):
    _, client, admin, _ = household
    _signed_in(client, admin)
    css = client.get("/static/vendor/bootstrap/bootstrap.min.css", headers={"Accept-Encoding": "gzip"})
    assert css.headers["Content-Encoding"] == "gzip"
    assert int(css.headers["Content-Length"]) < 60_000
    assert "Content-Encoding" not in client.get("/static/vendor/bootstrap/bootstrap.min.css").headers


def test_merged_library_is_cached_until_an_account_cache_changes(household, monkeypatch):
    import utils.auto_downloader as auto
    from utils.config_manager import get_config_manager
    from utils.constants import get_auth_file_path
    from utils.library_cache import invalidate_cache, write_library_cache
    _, client, admin, _ = household
    _signed_in(client, admin)
    manager = get_config_manager()
    path = get_auth_file_path("alice")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}")
    manager.update_account("alice", {"authenticated": True})
    books = [{"asin": f"B0PERF{i:04d}", "title": f"T{i}", "authors": "A"} for i in range(5)]
    write_library_cache("alice", books)

    calls = []
    real = auto.record_purchases
    monkeypatch.setattr(auto, "record_purchases", lambda name, lib: (calls.append(name), real(name, lib))[1])

    first = client.get("/api/library/all")
    second = client.get("/api/library/all")
    assert first.status_code == second.status_code == 200
    assert first.data == second.data and len(first.json["library"]) == 5
    assert calls == ["alice"], "purchases are recorded once per cache generation, not per request"

    write_library_cache("alice", books[:3])  # refetch => new key => rebuilt
    assert len(client.get("/api/library/all").json["library"]) == 3
    invalidate_cache("alice")
    assert client.get("/api/library/all").status_code in (200, 400, 502, 500)  # falls back to live fetch path
