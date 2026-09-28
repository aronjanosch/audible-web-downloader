"""Household discovery, durable ownership and cross-account download claims."""
import asyncio
from contextlib import nullcontext
from pathlib import Path

import pytest


@pytest.fixture
def database(tmp_path, monkeypatch):
    import utils.db as db
    old_path = db._db_path
    old_conn = getattr(db._local, 'conn', None)
    db._local.conn = None
    db.init_db(tmp_path / 'household.db')
    db.migrate()
    yield db.get_db()
    db._local.conn.close()
    db._local.conn = old_conn
    db._db_path = old_path


def test_shared_purchase_is_downloaded_once_and_attributed_to_both(database, tmp_path, monkeypatch):
    from utils.auto_downloader import run_auto_download
    import auth
    import downloader
    import utils.auto_downloader as automation

    database.execute("INSERT INTO accounts (name, region, authenticated) VALUES ('alice','us',1),('bob','us',1)")
    library_path = tmp_path / 'library'
    library_path.mkdir()
    database.execute("INSERT INTO libraries (name,path,created_at) VALUES ('home',?,0)", (str(library_path),))
    database.commit()

    purchases = {
        'alice': [{'asin': 'SHARED', 'title': 'Shared', 'authors': 'A. Writer',
                   'language': 'de', 'length_mins': 180}, {'asin': 'ALICE', 'title': 'Alice only'}],
        'bob': [{'asin': 'SHARED', 'title': 'Shared'}, {'asin': 'BOB', 'title': 'Bob only'}],
    }
    async def fetch(account_name, region):
        return purchases[account_name]
    calls = []
    async def download(account_name, region, books, library_path):
        calls.append((account_name, [book['asin'] for book in books]))
        result = []
        for book in books:
            path = Path(library_path) / (book['asin'] + '.m4b')
            path.write_bytes(b'book')
            result.append(str(path))
        return result
    monkeypatch.setattr(auth, 'fetch_library', fetch)
    monkeypatch.setattr(downloader, 'download_books', download)
    monkeypatch.setattr(automation, '_update_last_run', lambda *args: None)

    class App:
        app_context = staticmethod(nullcontext)

    for account in ('alice', 'bob'):
        run_auto_download(account, 'us', [], 'home', App())

    assert calls == [('alice', ['SHARED', 'ALICE']), ('bob', ['BOB'])]
    assert {(row['account_name'], row['asin']) for row in database.execute('SELECT * FROM account_books')} == {
        ('alice', 'SHARED'), ('alice', 'ALICE'), ('bob', 'SHARED'), ('bob', 'BOB')
    }
    assert {row['asin']: row['status'] for row in database.execute('SELECT asin,status FROM books')} == {
        'SHARED': 'downloaded', 'ALICE': 'downloaded', 'BOB': 'downloaded'
    }
    assert tuple(database.execute(
        "SELECT authors,language,runtime_length_min FROM books WHERE asin='SHARED'"
    ).fetchone()) == ('A. Writer', 'de', 180)


def test_failed_claim_is_retryable(database):
    from utils.auto_downloader import record_purchases, claim_downloads, finish_claims
    database.execute("INSERT INTO accounts (name,region) VALUES ('alice','us')")
    database.commit()
    book = {'asin': 'RETRY', 'title': 'Retry'}
    record_purchases('alice', [book])
    assert claim_downloads([book]) == [book]
    assert claim_downloads([book]) == []
    finish_claims([book], [])
    assert claim_downloads([book]) == [book]


def test_vanished_file_is_downloaded_on_next_poll(database, tmp_path, monkeypatch):
    from utils.auto_downloader import run_auto_download
    import auth
    import downloader
    import utils.auto_downloader as automation

    library_path = tmp_path / 'library'
    library_path.mkdir()
    vanished = library_path / 'vanished.m4b'
    database.execute("INSERT INTO accounts (name,region,authenticated) VALUES ('alice','us',1)")
    database.execute("INSERT INTO libraries (name,path,created_at) VALUES ('home',?,0)", (str(library_path),))
    database.execute(
        "INSERT INTO books (asin,title,status,file_path,added_at,updated_at) "
        "VALUES ('RETRY','Retry','downloaded',?,0,0)", (str(vanished),)
    )
    database.commit()

    async def fetch(*args):
        return [{'asin': 'RETRY', 'title': 'Retry'}]

    calls = []
    async def download(account_name, region, books, library_path):
        calls.append([book['asin'] for book in books])
        result = Path(library_path) / 'recovered.m4b'
        result.write_bytes(b'book')
        return [str(result)]

    monkeypatch.setattr(auth, 'fetch_library', fetch)
    monkeypatch.setattr(downloader, 'download_books', download)
    monkeypatch.setattr(automation, '_update_last_run', lambda *args: None)

    class App:
        app_context = staticmethod(nullcontext)

    run_auto_download('alice', 'us', [], 'home', App())
    assert calls == [['RETRY']]
    assert tuple(database.execute(
        "SELECT status,file_path FROM books WHERE asin='RETRY'"
    ).fetchone()) == ('downloaded', str(library_path / 'recovered.m4b'))


def test_unified_library_shows_all_owners(database, tmp_path, monkeypatch):
    import utils.constants as constants
    import utils.scheduler as scheduler
    import routes.auth as auth_routes
    from utils.security import create_user
    import time

    database.execute("INSERT INTO accounts (name,region,authenticated) VALUES ('alice','us',1),('bob','us',1)")
    database.commit()
    token_file = tmp_path / 'auth.json'
    token_file.write_text('{}')
    monkeypatch.setattr(constants, 'DB_FILE', tmp_path / 'household.db')
    monkeypatch.setattr(scheduler, 'init_scheduler', lambda app: None)
    monkeypatch.setattr(auth_routes, 'get_auth_file_path', lambda name: token_file)
    monkeypatch.setattr(auth_routes, 'get_cached_library', lambda name: [
        {'asin': 'SHARED', 'title': 'Shared book', 'authors': 'Author'}
    ])
    monkeypatch.setenv('SECRET_KEY', 'test-only-secret')
    monkeypatch.setenv('ADMIN_PASSWORD', 'admin-password-123')
    from app import create_app
    app = create_app()
    app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
    admin = dict(database.execute("SELECT id,username,role,account_name FROM users WHERE role='admin'").fetchone())
    client = app.test_client()
    with client.session_transaction() as session:
        session['user_id'] = admin['id']
        session['login_at'] = time.time()
    response = client.get('/api/library/all')
    assert response.status_code == 200
    assert response.json['library'] == [{
        'asin': 'SHARED', 'title': 'Shared book', 'authors': 'Author',
        'account_name': 'alice', 'account_names': ['alice', 'bob']
    }]
    assert database.execute('SELECT count(*) FROM account_books').fetchone()[0] == 2


def test_disabled_download_account_is_still_polled_for_new_purchases(database):
    from utils.scheduler import update_job, trigger_now
    database.execute("INSERT INTO accounts (name,region,authenticated,auto_dl_enabled) VALUES ('alice','us',1,0)")
    database.execute("INSERT INTO libraries (name,path,created_at) VALUES ('home','/tmp/home',0)")
    database.commit()

    class Scheduler:
        def __init__(self):
            self.jobs = {}
        def get_job(self, job_id):
            return self.jobs.get(job_id)
        def remove_job(self, job_id):
            del self.jobs[job_id]
        def add_job(self, function, **kwargs):
            self.jobs[kwargs['id']] = (function, kwargs)

    class App:
        scheduler = Scheduler()

    update_job(App(), 'alice', {'enabled': False, 'interval_hours': 6})
    assert 'auto_download_alice' in App.scheduler.jobs
    assert App.scheduler.jobs['auto_download_alice'][1]['kwargs']['downloads_enabled'] is False
    assert 'audible_probe_alice' in App.scheduler.jobs
    trigger_now(App(), 'alice')
    assert App.scheduler.jobs['auto_download_alice_manual'][1]['kwargs']['default_library_name'] == 'home'
