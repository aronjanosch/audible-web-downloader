# AGENTS.md

Working notes for AI coding agents in this repository. Facts about how the project
runs today — not a spec. The active objective and its Definition of Done live in
`GOAL.md` / the Codex `/goal`. When in doubt, keep the product running and the data
safe, then keep improving.

## What this is

A self-hosted, always-on web app that lets a household pool their Audible purchases
into one library. Family and friends self-serve their own Audible account through an
invite link, authenticate themselves, and the app downloads, decrypts and organizes
their books into a shared Audiobookshelf/Plex library. Private tool for books people
already own — never a redistribution or public-piracy service.

## Build / run / test

```bash
# Install (uv manages deps; uv.lock is the source of truth)
uv sync

# Run locally
./dev.sh                      # dev server on http://localhost:5505
# or
uv run python run.py

# Production-style serve
uv run gunicorn -c gunicorn.conf.py "app:create_app()"

# Tests
uv run pytest                 # there is currently no pytest config / conftest; add one if useful

# Docker (published image; needs SECRET_KEY in .env — see docs/deployment.md)
docker compose pull && docker compose up -d
ruff check .                  # correctness lint (bug-class rules only)
node --test tests/dom_escaping.test.cjs
```

Python `3.13` (see `.python-version`). ffmpeg is required at runtime for AAX→M4B.

## Current architecture (as-is)

- **Flask** app factory in `app/__init__.py`; blueprints in `routes/`
  (`main`, `auth`, `download`, `library`, `invite`, `importer`, `scheduler`, `books`,
  `security`, `household`, `health`). UI: design tokens + shared components in
  `static/css/app.css` ("Audible Redesign" system, DM Sans, warm paper/green/amber), page CSS/JS
  beside it; top bar + queue drawer live in `templates/base.html` / `static/js/queue-drawer.js`.
- **Persistence:** raw `sqlite3` in `utils/db.py`, WAL mode, thread-local connections,
  hand-rolled migrations keyed on `PRAGMA user_version` (currently `SCHEMA_VERSION = 5`).
  Legacy JSON (`accounts.json`, `libraries.json`, `library.json`) is imported once on
  first migrate.
- **Queues:** in-memory, process-level singletons in `utils/queue_base.py`
  (`DownloadQueueManager`, `ImportQueueManager`); progress streamed over SSE.
- **Scheduling:** APScheduler (`utils/scheduler.py`) for periodic library checks /
  auto-download.
- **Audible:** the `audible` library for auth + library access; ffmpeg for decryption
  and AAX→M4B conversion (`downloader.py`, `app/services/`).
- **Config paths:** resolved in `utils/constants.py` (`config/`, `downloads/`,
  `library_data/`); per-account Audible tokens under `config/auth/<account>/auth.json`.

## Guardrails (do not break)

- **`gunicorn.conf.py` pins `workers = 1` on purpose.** The download/import queues are
  in-memory singletons, so multiple worker processes would each hold a separate queue
  and the SSE UI would go stale. Fix the architecture before raising the worker count —
  don't just bump it.
- **Never commit secrets or real state.** No real `config/`, `auth/`, tokens, `audible.db`,
  or `.env` values. `SECRET_KEY` must come from the environment in production.
- **Migrations must be additive and idempotent.** Existing installs must never lose data
  or get locked out. If you change the schema or config format, migrate forward and keep
  the old data readable.
- **Keep it self-hosted and simple to deploy.** One compose file, one app.
- **Stay in scope:** backing up books people own for their own household. Do not add
  redistribution/sharing of decrypted content or weaken existing DRM handling.

## Conventions

- Dependencies via `uv`; keep `uv.lock` in sync (`uv sync`).
- Keep setup guidance in this file and `README.md`; editor-specific instruction
  folders are not part of this project.
- Prefer small, reviewable changes with a test or a runnable check for each.

## Parallel workstreams

The work splits into largely independent tracks. Where your tooling supports subagents,
explore them in parallel and converge rather than serializing everything:

- security / auth (per-user accounts, roles, sessions, rate limiting, headers)
- frontend / UX (framework choice, redesign, responsiveness)
- Audiobookshelf integration depth
- Audible token lifecycle (refresh, expiry detection, member self-service re-auth)
- tests / CI / migration safety

## Reporting

When you claim something is done, name the evidence — the test, command, measurement or
output that proves it. Separate what is proven from what is approximate and what is open.
