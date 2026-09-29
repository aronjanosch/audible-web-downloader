# Audible Web Downloader

A self-hosted web app that lets a household pool their **Audible purchases into one shared
audiobook library**. Family and friends connect their own Audible account through an invite link;
the app downloads, decrypts and organizes their books into a folder that
[Audiobookshelf](https://www.audiobookshelf.org/) (or Plex) serves.

> **Scope.** This is a private backup tool for books you (or your household) have already bought.
> It is not a redistribution or piracy service, and contributions that make it one will be declined.
> You are responsible for complying with Audible's terms and the copyright law where you live.

<!-- Screenshots: add PNGs under docs/screenshots/ (library, queue drawer, household, settings)
     and embed them here, e.g. ![Library](docs/screenshots/library.png). Use placeholder names only. -->

## Features

- **Household accounts** – admin and member roles; each member manages only their own Audible account.
- **Library** – grid / list / series views, status filters (new, downloaded, queued, duplicates), search by title, author, narrator or ASIN, one-click batch download with size estimate.
- **Household-aware duplicates** – a book owned by several accounts is downloaded once.
- **Automatic downloads** – new purchases from any linked account are detected and queued.
- **Live queue** – progress with steps (download → decrypt → convert → tag → Audiobookshelf) in a drawer available on every page.
- **Long-lived Audible tokens** – automatic refresh, expiry/revocation detection, member self-service reconnect. See [docs/token-lifecycle.md](docs/token-lifecycle.md).
- **Audiobookshelf integration** – scan trigger, ASIN/title matching, status sync. See [docs/audiobookshelf.md](docs/audiobookshelf.md).
- **M4B import** – bring existing files into the library with Audible metadata matching.
- **Household overview** – token health, needs-attention list, activity feed.
- **Responsive UI**, light and dark mode, all regions supported by Audible.

## Quickstart (Docker Compose)

Requirements: Docker with Compose v2. A reverse proxy with HTTPS is needed for sign-in over the internet (see below).

```bash
git clone https://github.com/aronjanosch/audible-web-downloader.git
cd audible-web-downloader
cp .env.example .env
python3 -c "import secrets; print(secrets.token_urlsafe(48))"    # paste as SECRET_KEY in .env
mkdir -p config downloads library library_data
sudo chown -R 1000:1000 config downloads library library_data     # container runs as uid 1000
docker compose up -d
```

Open <http://localhost:5505>. Get the generated admin credentials from
`config/initial-admin-credentials.json` (or set `ADMIN_USERNAME` / `ADMIN_PASSWORD` in `.env` before
the first start), sign in, then **delete that file**. Add an Audible account, invite your household,
and point Audiobookshelf at the `library/` folder.

The app **will not start without a real `SECRET_KEY`**. To pull instead of build, use a tagged image:
`AUDIBLE_IMAGE=ghcr.io/aronjanosch/audible-web-downloader:1.0.0` in `.env`.

Full deployment guide (reverse proxy snippets for Caddy and nginx, backup/restore, upgrades,
troubleshooting): **[docs/deployment.md](docs/deployment.md)**.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `SECRET_KEY` | required | Signs session cookies. |
| `ADMIN_USERNAME`, `ADMIN_PASSWORD` | `admin`, generated | First-boot admin only. |
| `SESSION_COOKIE_SECURE` | `1` | Cookies are HTTPS-only. Set `0` for plain HTTP on a trusted LAN. |
| `TRUSTED_PROXIES` | `0` | Reverse-proxy hops to trust for `X-Forwarded-*` (needed for per-IP login rate limiting). |
| `LOG_LEVEL` | `INFO` | Credential-looking values are masked in logs. |
| `TZ` | `UTC` | Timezone. |
| `BIND_ADDRESS`, `PORT` | `127.0.0.1`, `5505` | Published address (Compose). |
| `ABS_URL`, `ABS_API_TOKEN`, `ABS_LIBRARY_ID` | empty | Audiobookshelf (all three or none). |

Persistent data: `config/` (database, settings, **Audible tokens** – back this up, encrypted),
`library/` (finished audiobooks), `downloads/` (temporary), `library_data/` (cache).

## How Audible sign-in works

Amazon's login happens on Amazon's own page; your password never reaches this app. The app stores
a revocable device token under `config/auth/<account>/auth.json` (mode 0600). Access tokens are
refreshed automatically (they last about an hour). If Amazon revokes a token, the account shows
**Expired** in the household overview and the member reconnects from their own home page – no admin
needed. Amazon documents refresh tokens as valid until the customer revokes them, with no fixed
maximum lifetime; details and sources in [docs/token-lifecycle.md](docs/token-lifecycle.md).

## Security model

Hashed passwords, 12-hour sessions, CSRF protection, login rate limiting, security headers,
role checks on every route (asserted by tests), non-root container with read-only root filesystem
support. See [SECURITY.md](SECURITY.md) and [docs/threat-model.md](docs/threat-model.md).
Always serve it over HTTPS when it is reachable from the internet.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Exits with `SECRET_KEY is not set` | Set a random `SECRET_KEY` in `.env`. |
| Sign-in reloads without an error | You are on plain HTTP with secure cookies: use HTTPS, or `SESSION_COOKIE_SECURE=0` on a LAN. |
| `Permission denied` on `config/` | `sudo chown -R 1000:1000 config downloads library library_data`. |
| Everyone gets "too many attempts" | Behind a proxy, set `TRUSTED_PROXIES=1`. |
| Progress does not update | Disable response buffering for the app in your proxy (SSE). |
| Account shows "Expired" | The member reconnects Audible from their home page. |

More in [docs/deployment.md](docs/deployment.md#9-troubleshooting). Health probe: `GET /healthz`.

## Development

```bash
uv sync                                                 # Python 3.13, uv.lock is the source of truth
FLASK_ENV=development SESSION_COOKIE_SECURE=0 ./dev.sh  # http://localhost:5505
uv run pytest && uv run ruff check . && node --test tests/dom_escaping.test.cjs
```

ffmpeg is required for AAX → M4B conversion. Architecture notes and guardrails (single gunicorn
worker, additive migrations) are in [AGENTS.md](AGENTS.md); contribution guide in
[CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE)
