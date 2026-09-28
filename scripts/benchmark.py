"""Measure Flask page and API latency with an isolated empty installation.

Run with PYTHONPATH pointing at the source tree to compare revisions. Results
are local test-client medians, not network or browser paint times.
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
        print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
