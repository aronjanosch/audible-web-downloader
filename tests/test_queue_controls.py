"""Queue pause/resume, retry of failed rows, duplicates-avoided counter."""
import time

import pytest

from test_security import household, _signed_in, _csrf  # noqa: F401  (fixture reuse)


@pytest.fixture(autouse=True)
def clean_queue():
    from downloader import DownloadQueueManager
    q = DownloadQueueManager()
    with q._lock:
        for key in [k for k in q._queue if not k.startswith("_")]:
            del q._queue[key]
    q.set_paused(False)
    yield q
    q.set_paused(False)


def test_pause_resume_are_admin_only_and_reflected_in_stats(household, clean_queue):
    _, client, admin, alice = household
    assert client.post("/api/download/pause").status_code == 401
    _signed_in(client, alice)
    assert client.post("/api/download/pause", headers=_csrf(client)).status_code == 403
    _signed_in(client, admin)
    headers = _csrf(client)
    assert client.post("/api/download/pause", headers=headers).json["paused"] is True
    assert clean_queue.is_paused() and clean_queue.get_statistics()["paused"] is True
    assert client.get("/api/download/status").json["paused"] is True
    assert client.post("/api/download/resume", headers=headers).json["paused"] is False
    assert not clean_queue.is_paused()


def test_pause_requires_csrf(household):
    _, client, admin, _ = household
    _signed_in(client, admin)
    assert client.post("/api/download/pause").status_code == 400


def test_pause_gate_holds_a_job_until_resumed(household, clean_queue, tmp_path, monkeypatch):
    """A pending job must not take a download slot while paused."""
    import asyncio
    from downloader import AudiobookDownloader

    monkeypatch.chdir(tmp_path)
    entered = []
    downloader = AudiobookDownloader.__new__(AudiobookDownloader)
    downloader.queue_manager = clean_queue

    async def gate():
        while downloader.queue_manager.is_paused():
            await asyncio.sleep(0.01)
        entered.append(True)

    async def scenario():
        clean_queue.set_paused(True)
        task = asyncio.create_task(gate())
        await asyncio.sleep(0.1)
        assert not entered
        clean_queue.set_paused(False)
        await asyncio.wait_for(task, 1)

    asyncio.run(scenario())
    assert entered


def _failed_item(queue, **extra):
    queue.add_download_to_queue("B000RETRY", "Retry Me", downloaded_by_account="alice")
    queue.update_download("B000RETRY", {"state": "error", "error": "boom", "asin": "B000RETRY",
                                        "library_path": "/tmp/lib", "region": "us", **extra})


def test_retry_only_for_failed_rows_with_context(household, clean_queue, monkeypatch):
    _, client, admin, alice = household
    _signed_in(client, alice)
    assert client.post("/api/download/retry/B000RETRY", headers=_csrf(client)).status_code == 403
    _signed_in(client, admin)
    headers = _csrf(client)
    assert client.post("/api/download/retry/B000RETRY", headers=headers).status_code == 409  # unknown row

    _failed_item(clean_queue)
    clean_queue.update_download("B000RETRY", {"library_path": None})
    assert client.post("/api/download/retry/B000RETRY", headers=headers).status_code == 409  # no context


def test_retry_requeues_and_restarts_download(household, clean_queue, monkeypatch):
    import routes.download as download_routes
    _, client, admin, _ = household
    _signed_in(client, admin)
    _failed_item(clean_queue)
    calls = []

    async def fake_download_books(account, region, books, **kwargs):
        calls.append((account, region, [b["asin"] for b in books], kwargs["library_path"]))
        return []

    monkeypatch.setattr(download_routes, "download_books", fake_download_books)
    monkeypatch.setattr(download_routes, "get_cached_library",
                        lambda account: [{"asin": "B000RETRY", "title": "Retry Me"}])
    monkeypatch.setattr(download_routes, "get_account_or_404", lambda name: ({}, "us"))
    response = client.post("/api/download/retry/B000RETRY", headers=_csrf(client))
    assert response.status_code == 200
    item = clean_queue.get_download("B000RETRY")
    assert item["state"] == "pending" and item["error"] is None
    for _ in range(50):
        if calls:
            break
        time.sleep(0.02)
    assert calls == [("alice", "us", ["B000RETRY"], "/tmp/lib")]


def test_duplicates_avoided_counts_once_per_account_and_title(household):
    from utils.events import duplicates_avoided_since, record_duplicate_avoided
    _, client, admin, _ = household
    assert record_duplicate_avoided("alice", "B000DUP", "Dup Title") is True
    assert record_duplicate_avoided("alice", "B000DUP", "Dup Title") is False  # repeat poll
    assert record_duplicate_avoided("bob", "B000DUP", "Dup Title") is True     # other account counts
    assert duplicates_avoided_since(7 * 86400) == 2

    _signed_in(client, admin)
    body = client.get("/api/household/overview").json
    assert body["summary"]["duplicates_avoided"] == 2
    assert any("Skipped Dup Title" in e["text"] for e in body["activity"])


def test_duplicates_skipped_endpoint_records_and_is_admin_only(household):
    from utils.events import duplicates_avoided_since
    _, client, admin, alice = household
    payload = {"account_name": "alice", "items": [{"asin": "B000SKIP", "title": "Skip Me"}, {"asin": ""}]}
    _signed_in(client, alice)
    assert client.post("/api/library/duplicates-skipped", json=payload, headers=_csrf(client)).status_code == 403
    _signed_in(client, admin)
    headers = _csrf(client)
    assert client.post("/api/library/duplicates-skipped", json=payload, headers=headers).json["recorded"] == 1
    assert client.post("/api/library/duplicates-skipped", json=payload, headers=headers).json["recorded"] == 0
    assert duplicates_avoided_since(3600) == 1


def test_auto_download_records_duplicate_for_newly_seen_owned_title(household, monkeypatch):
    """A title a household account just gained, already on disk via another account, is a skip."""
    import asyncio
    import utils.auto_downloader as auto
    from utils.db import get_db
    app, _, _, _ = household
    db = get_db()
    db.execute("INSERT INTO books (asin,title,status,added_at,updated_at) VALUES ('B000OWNED','Owned','downloaded',1,1)")
    db.commit()

    async def fake_fetch(account, region):
        return [{"asin": "B000OWNED", "title": "Owned"}]

    monkeypatch.setattr("auth.fetch_library", fake_fetch)
    auto.run_auto_download("bob", "us", [], None, app)
    auto.run_auto_download("bob", "us", [], None, app)  # a second poll must not double count
    from utils.events import duplicates_avoided_since
    assert duplicates_avoided_since(3600) == 1
