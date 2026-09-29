# Contributing

Thanks for helping. Keep changes small, tested, and in scope (self-hosted, simple to deploy,
books you own — see [AGENTS.md](AGENTS.md)).

## Setup

```bash
uv sync                       # Python 3.13; uv.lock is the source of truth
FLASK_ENV=development SESSION_COOKIE_SECURE=0 ./dev.sh    # http://localhost:5505
```

ffmpeg must be installed to convert AAX → M4B.

## Before opening a PR

```bash
uv run pytest
uv run ruff check .
node --test tests/dom_escaping.test.cjs
```

- Add a test or a runnable check for each change.
- Schema/config changes must be **additive and idempotent** (see `utils/db.py`); existing installs
  must never lose data.
- Do not raise gunicorn `workers` above 1 (in-memory queues; see AGENTS.md).
- Escape all dynamic text in the browser (`textContent` or the existing escape helpers).
- Never commit secrets, real `config/`, tokens, `.env`, or screenshots containing personal data.
- Use placeholder names in tests, fixtures and docs.

## Commit style

Short imperative subject, body explains why.
