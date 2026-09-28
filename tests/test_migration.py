"""Forward migration from the pre-login SQLite and JSON install preserves data."""
import json
import sqlite3
import pytest


def test_legacy_sqlite_and_json_forward_migration_is_idempotent(tmp_path, monkeypatch):
    import utils.constants as constants
    import utils.db as db

    config_dir = tmp_path / 'config'
    config_dir.mkdir()
    library_data_dir = tmp_path / 'library_data'
    library_data_dir.mkdir()
    auth_dir = config_dir / 'auth' / 'alice'
    auth_dir.mkdir(parents=True)
    (auth_dir / 'auth.json').write_text('{"refresh_token":"legacy-secret"}')
    (config_dir / 'settings.json').write_text('{"naming_pattern":"{Title}"}')
    (config_dir / 'accounts.json').write_text(json.dumps({
        'alice': {'region': 'de', 'authenticated': True, 'auto_download': {
            'enabled': True, 'default_library_name': 'home', 'rules': [
                {'field': 'language', 'value': 'de', 'library_name': 'home'}
            ]}}
    }))
    (config_dir / 'libraries.json').write_text(json.dumps({'home': {'path': str(tmp_path / 'books')}}))
    (config_dir / 'library.json').write_text(json.dumps({
        'B001': {'title': 'Owned Book', 'state': 'converted', 'file_path': '/old/B001.m4b',
                 'downloaded_by_account': 'alice', 'library_name': 'home',
                 'authors': [{'name': 'A. Writer'}], 'series': [{'title': 'A Series'}],
                 'narrators': ['N. Voice'], 'language': 'de', 'runtime_length_min': 420,
                 'file_size_bytes': 123456}
    }))
    (library_data_dir / 'libraries.json').write_text(json.dumps({
        'home': {'path': str(tmp_path / 'books'), 'books': [
            {'asin': 'B001', 'title': 'Owned Book', 'file_path': '/old/B001.m4b',
             'authors': 'A. Writer'}
        ]}
    }))
    monkeypatch.setattr(constants, 'CONFIG_DIR', config_dir)
    monkeypatch.setattr(constants, 'ACCOUNTS_FILE', config_dir / 'accounts.json')
    monkeypatch.setattr(constants, 'LIBRARIES_FILE', config_dir / 'libraries.json')
    monkeypatch.setattr(constants, 'LIBRARY_DATA_DIR', library_data_dir)

    previous_path = db._db_path
    previous_conn = getattr(db._local, 'conn', None)
    db._local.conn = None
    try:
        db.init_db(config_dir / 'audible.db')
        db.migrate()
        conn = db.get_db()
        assert conn.execute('SELECT region FROM accounts WHERE name=?', ('alice',)).fetchone()[0] == 'de'
        assert conn.execute('SELECT status, file_path FROM books WHERE asin=?', ('B001',)).fetchone()['status'] == 'downloaded'
        migrated = conn.execute('SELECT authors,series,narrator,language,runtime_length_min,file_size_bytes FROM books WHERE asin=?', ('B001',)).fetchone()
        assert tuple(migrated) == ('A. Writer', 'A Series', 'N. Voice', 'de', 420, 123456)
        assert conn.execute('SELECT count(*) FROM auto_download_rules').fetchone()[0] == 1
        assert conn.execute('SELECT path FROM libraries WHERE name=?', ('home',)).fetchone()[0] == str(tmp_path / 'books')
        assert conn.execute('SELECT asin,file_path FROM scan_cache').fetchone()['asin'] == 'B001'

        # Simulate a pre-login v3 installation with user data and a JSON backup.
        conn.execute('PRAGMA user_version=3')
        conn.commit()
        before = [tuple(row) for row in conn.execute('SELECT * FROM books')]
        db.migrate()
        assert conn.execute('PRAGMA user_version').fetchone()[0] == db.SCHEMA_VERSION
        assert conn.execute("SELECT name FROM sqlite_master WHERE name='users'").fetchone()
        assert [tuple(row) for row in conn.execute('SELECT * FROM books')] == before
        assert conn.execute('SELECT count(*) FROM accounts').fetchone()[0] == 1
        assert conn.execute('SELECT count(*) FROM auto_download_rules').fetchone()[0] == 1
        db.migrate()
        assert [tuple(row) for row in conn.execute('SELECT * FROM books')] == before
        conn.execute("UPDATE books SET status='downloading' WHERE asin='B001'")
        conn.commit()
        db.migrate()
        assert conn.execute("SELECT status FROM books WHERE asin='B001'").fetchone()[0] == 'wanted'
        assert (config_dir / 'library.json').exists()
        assert (config_dir / 'accounts.json').exists()
        assert (auth_dir / 'auth.json').read_text() == '{"refresh_token":"legacy-secret"}'
        assert (config_dir / 'settings.json').read_text() == '{"naming_pattern":"{Title}"}'
        assert (library_data_dir / 'libraries.json').exists()
    finally:
        db._local.conn.close()
        db._local.conn = previous_conn
        db._db_path = previous_path


def test_corrupt_legacy_json_stops_migration_without_erasing_source(tmp_path, monkeypatch):
    import utils.constants as constants
    import utils.db as db

    legacy_file = tmp_path / 'accounts.json'
    legacy_file.write_text('{bad json')
    monkeypatch.setattr(constants, 'ACCOUNTS_FILE', legacy_file)
    monkeypatch.setattr(constants, 'LIBRARIES_FILE', tmp_path / 'libraries.json')
    monkeypatch.setattr(constants, 'CONFIG_DIR', tmp_path)
    monkeypatch.setattr(constants, 'LIBRARY_DATA_DIR', tmp_path / 'library_data')
    previous_path = db._db_path
    previous_conn = getattr(db._local, 'conn', None)
    db._local.conn = None
    try:
        db.init_db(tmp_path / 'audible.db')
        with pytest.raises(RuntimeError, match='unreadable legacy file'):
            db.migrate()
        assert legacy_file.read_text() == '{bad json'
        assert db.get_db().execute('PRAGMA user_version').fetchone()[0] == 0
    finally:
        db._local.conn.close()
        db._local.conn = previous_conn
        db._db_path = previous_path


def test_upgrade_bootstraps_retrievable_admin_without_touching_accounts(tmp_path, monkeypatch):
    import utils.constants as constants
    import utils.db as db
    from utils.security import bootstrap_admin, verify_user

    monkeypatch.setattr(constants, 'CONFIG_DIR', tmp_path)
    monkeypatch.setattr(constants, 'ACCOUNTS_FILE', tmp_path / 'accounts.json')
    monkeypatch.setattr(constants, 'LIBRARIES_FILE', tmp_path / 'libraries.json')
    monkeypatch.setattr(constants, 'LIBRARY_DATA_DIR', tmp_path / 'library_data')
    monkeypatch.delenv('ADMIN_PASSWORD', raising=False)
    previous_path = db._db_path
    previous_conn = getattr(db._local, 'conn', None)
    db._local.conn = None
    try:
        db.init_db(tmp_path / 'audible.db')
        db.migrate()
        conn = db.get_db()
        conn.execute("INSERT INTO accounts (name,region,authenticated) VALUES ('legacy','de',1)")
        conn.commit()
        bootstrap_admin()
        credential_file = tmp_path / 'initial-admin-credentials.json'
        credentials = json.loads(credential_file.read_text())
        assert credential_file.stat().st_mode & 0o777 == 0o600
        assert verify_user(credentials['username'], credentials['password'])['role'] == 'admin'
        bootstrap_admin()
        assert json.loads(credential_file.read_text()) == credentials
        assert tuple(conn.execute('SELECT region,authenticated FROM accounts WHERE name=?', ('legacy',)).fetchone()) == ('de', 1)
        assert conn.execute("SELECT count(*) FROM users WHERE role='admin'").fetchone()[0] == 1
    finally:
        db._local.conn.close()
        db._local.conn = previous_conn
        db._db_path = previous_path


def test_existing_v3_database_with_json_backups_upgrades_in_place(tmp_path, monkeypatch):
    import utils.constants as constants
    import utils.db as db

    config_dir = tmp_path / 'config'
    config_dir.mkdir()
    backup = config_dir / 'accounts.json'
    backup.write_text('{"alice":{"region":"de","authenticated":true}}')
    monkeypatch.setattr(constants, 'ACCOUNTS_FILE', backup)
    monkeypatch.setattr(constants, 'CONFIG_DIR', config_dir)
    monkeypatch.setattr(constants, 'LIBRARIES_FILE', config_dir / 'libraries.json')
    monkeypatch.setattr(constants, 'LIBRARY_DATA_DIR', tmp_path / 'library_data')
    path = config_dir / 'audible.db'
    legacy = sqlite3.connect(path)
    legacy.executescript('''
        PRAGMA foreign_keys=ON;
        CREATE TABLE accounts (name TEXT PRIMARY KEY, region TEXT NOT NULL,
            authenticated INTEGER NOT NULL DEFAULT 0, auto_dl_enabled INTEGER NOT NULL DEFAULT 0,
            auto_dl_interval_hours INTEGER NOT NULL DEFAULT 6, auto_dl_default_library TEXT,
            auto_dl_last_run TEXT, auto_dl_last_run_result TEXT, pending_invitation_token TEXT);
        CREATE TABLE libraries (name TEXT PRIMARY KEY, path TEXT NOT NULL UNIQUE, created_at REAL NOT NULL);
        CREATE TABLE books (asin TEXT PRIMARY KEY, title TEXT NOT NULL, authors TEXT,
            series TEXT, narrator TEXT, publisher TEXT, language TEXT, runtime_length_min INTEGER,
            status TEXT NOT NULL, file_path TEXT, file_size_bytes INTEGER, last_seen_on_disk REAL,
            library_name TEXT REFERENCES libraries(name) ON DELETE SET NULL,
            downloaded_by_account TEXT REFERENCES accounts(name) ON DELETE SET NULL,
            added_at REAL NOT NULL, updated_at REAL NOT NULL);
        CREATE TABLE auto_download_rules (id INTEGER PRIMARY KEY, account_name TEXT NOT NULL,
            position INTEGER NOT NULL, field TEXT NOT NULL, value TEXT NOT NULL, library_name TEXT NOT NULL);
        CREATE TABLE scan_cache (id INTEGER PRIMARY KEY, library_name TEXT NOT NULL,
            file_path TEXT NOT NULL UNIQUE, asin TEXT, title TEXT, authors TEXT, series TEXT,
            narrator TEXT, year TEXT, language TEXT, file_size INTEGER,
            duration_sec REAL, last_scanned REAL NOT NULL);
        CREATE TABLE library_cache (account_name TEXT PRIMARY KEY, fetched_at REAL NOT NULL,
            books_json TEXT NOT NULL);
        INSERT INTO accounts (name,region,authenticated) VALUES ('alice','de',1);
        INSERT INTO libraries (name,path,created_at) VALUES ('home','/library',1);
        INSERT INTO books (asin,title,status,file_path,library_name,downloaded_by_account,added_at,updated_at)
            VALUES ('B001','Owned Book','downloaded','/library/B001.m4b','home','alice',1,1);
        INSERT INTO library_cache (account_name,fetched_at,books_json)
            VALUES ('alice',1,'[{"asin":"B001"}]');
        PRAGMA user_version=3;
    ''')
    before = [tuple(row) for row in legacy.execute('SELECT * FROM books')]
    legacy.close()
    previous_path = db._db_path
    previous_conn = getattr(db._local, 'conn', None)
    db._local.conn = None
    try:
        db.init_db(path)
        db.migrate()
        conn = db.get_db()
        assert conn.execute('PRAGMA user_version').fetchone()[0] == db.SCHEMA_VERSION
        assert [tuple(row) for row in conn.execute('SELECT * FROM books')] == before
        assert conn.execute('SELECT books_json FROM library_cache').fetchone()[0] == '[{"asin":"B001"}]'
        assert all(conn.execute('SELECT 1 FROM sqlite_master WHERE name=?', (name,)).fetchone()
                   for name in ('users', 'account_books', 'abs_items'))
        assert backup.read_text() == '{"alice":{"region":"de","authenticated":true}}'
        db.migrate()
        assert [tuple(row) for row in conn.execute('SELECT * FROM books')] == before
    finally:
        db._local.conn.close()
        db._local.conn = previous_conn
        db._db_path = previous_path
