"""Measure Flask page and API latency with an isolated installation.

Run with PYTHONPATH pointing at the source tree to compare revisions. Results
are local test-client medians, not network or browser paint times.

  uv run python scripts/benchmark.py              # empty install + populated household (BENCH_BOOKS, default 1500)
  BENCH_BOOKS=0 uv run python scripts/benchmark.py  # empty install only
"""
import json
import os
import statistics
import tempfile
import time
from pathlib import Path


def measure(client, path, samples=51):
    timings = []
    size = 0
    for _ in range(samples):
        start = time.perf_counter()
        response = client.get(path)
        timings.append((time.perf_counter() - start) * 1000)
        if response.status_code != 200:
            raise RuntimeError(f'{path}: HTTP {response.status_code}')
        size = len(response.data)
    ordered = sorted(timings)
    return {'median_ms': round(statistics.median(timings), 3),
            'p95_ms': round(ordered[int(.95 * (samples - 1))], 3),
            'bytes': size}


def populate(root, books):
    """3 authenticated accounts sharing a fake purchase list, some titles downloaded. Fake data only."""
    import utils.library_cache as library_cache
    from utils.config_manager import get_config_manager
    from utils.db import get_db
    manager = get_config_manager()
    names = ['member-a', 'member-b', 'member-c']
    for name in names:
        manager.create_account(name, {'region': 'us', 'authenticated': True})
        auth = root / 'auth' / name
        auth.mkdir(parents=True, exist_ok=True)
        (auth / 'auth.json').write_text('{}')
    catalog = [{'asin': f'B0BENCH{i:05d}', 'title': f'Benchmark Title {i}', 'authors': f'Author {i % 40}',
                'series': f'Series {i % 60}', 'narrator': f'Narrator {i % 25}', 'publisher': 'Bench Press',
                'language': 'english', 'length_mins': 300 + i % 600, 'release_year': str(2000 + i % 25),
                'cover_url': ''} for i in range(books)]
    for index, name in enumerate(names):
        library_cache.write_library_cache(name, [dict(b, account_name=name) for b in catalog[index::2] + catalog[:books // 4]])
    db = get_db()
    now = time.time()
    with db:
        for i, book in enumerate(catalog[:books // 3]):
            db.execute("INSERT OR IGNORE INTO books (asin,title,status,added_at,updated_at,file_path,downloaded_by_account)"
                       " VALUES (?,?,'downloaded',?,?,?,?)", (book['asin'], book['title'], now, now,
                                                            f"/library/{book['authors']}/{book['title']}/book.m4b", names[i % 3]))


def main():
    with tempfile.TemporaryDirectory(prefix='audible-bench-') as root:
        import utils.constants as constants
        import utils.scheduler as scheduler
        root = Path(root)
        constants.CONFIG_DIR = root
        constants.AUTH_DIR = root / 'auth'
        constants.DB_FILE = root / 'audible.db'
        constants.ACCOUNTS_FILE = root / 'accounts.json'
        constants.LIBRARIES_FILE = root / 'libraries.json'
        constants.LIBRARY_DATA_DIR = root / 'library_data'
        scheduler.init_scheduler = lambda app: None
        os.environ['SECRET_KEY'] = 'benchmark-only-key'
        from app import create_app
        app = create_app()
        app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
        client = app.test_client()
        try:
            from utils.security import create_user
        except ImportError:
            pass
        else:
            user = create_user('benchmark', 'benchmark-password-123', 'admin')
            with client.session_transaction() as sess:
                sess['user_id'] = user['id']
                sess['login_at'] = time.time()
        result = {'revision': os.environ.get('BENCH_REVISION', 'working-tree'),
                  'page': measure(client, '/'), 'api': measure(client, '/api/accounts')}
        books = int(os.environ.get('BENCH_BOOKS', '1500'))
        if books:
            populate(root, books)
            result['populated_books'] = books
            for path in ('/api/library/all', '/api/library/household', '/api/household/overview',
                         '/api/session', '/', '/household', '/settings', '/downloads'):
                result[path] = measure(client, path, samples=21)
        print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
