# Deployment guide

This app is a single container with one gunicorn worker (on purpose — see
[AGENTS.md](../AGENTS.md)). It stores everything under four directories, which you
mount as volumes:

| Path in container | Purpose | Back up? |
|---|---|---|
| `/app/config` | SQLite database (`audible.db`), `settings.json`, per-account Audible tokens under `auth/` | **Yes — contains credentials** |
| `/app/library` | Final organized M4B audiobooks (point Audiobookshelf/Plex here) | Yes (large) |
| `/app/downloads` | Temporary AAX/voucher/conversion files | No |
| `/app/library_data` | Cached library scan data | No (rebuilt) |

## 1. First start

```bash
git clone https://github.com/aronjanosch/audible-web-downloader.git
cd audible-web-downloader
cp .env.example .env
python3 -c "import secrets; print(secrets.token_urlsafe(48))"   # paste into SECRET_KEY in .env
mkdir -p config downloads library library_data
sudo chown -R 1000:1000 config downloads library library_data    # the container runs as uid 1000
docker compose up -d
docker compose ps                                                # should become "healthy"
```

The app **refuses to start without a real `SECRET_KEY`** (unset or placeholders such as
`change-me`). For local development only, `FLASK_ENV=development` allows an ephemeral key.

### First admin

On the first boot with an empty user table the app creates one admin:

- **You set the password:** put `ADMIN_USERNAME` / `ADMIN_PASSWORD` (12+ characters) in `.env`
  for the first start, then remove `ADMIN_PASSWORD` from `.env`.
- **Or let the app generate it:** leave `ADMIN_PASSWORD` empty; read
  `config/initial-admin-credentials.json` (mode 0600), sign in, change your workflow to a
  password manager, and **delete that file**.

Afterwards the admin invites household members from the app; each member sets their own
password and connects their own Audible account. Upgrading an install that predates
household sign-in keeps all existing accounts, books and tokens.

## 2. HTTPS and reverse proxy

Session cookies are `Secure` by default, so **sign-in only works over HTTPS** (or on
`localhost`). Keep the container on loopback (`BIND_ADDRESS=127.0.0.1`, the default) and
terminate TLS in a reverse proxy.

Tell the app how many proxies sit in front of it with `TRUSTED_PROXIES` (default `0`).
Only then are `X-Forwarded-For/-Proto/-Host` honored. This matters for two things:
the **login rate limit is keyed by client IP** (without it every user shares the proxy's IP
and one attacker locks everyone out), and HTTPS detection. Never set it if the app is
reachable directly without the proxy, or clients could spoof their address.

Two things the proxy must allow:
- **Server-Sent Events** on `/api/download/progress-stream` — disable response buffering
  and use long read timeouts.
- Large streaming responses without a request-size cap issue.

### Caddy

```caddyfile
audible.example.com {
    reverse_proxy 127.0.0.1:5505 {
        flush_interval -1
    }
}
```
`.env`: `TRUSTED_PROXIES=1`

### nginx

```nginx
server {
    listen 443 ssl http2;
    server_name audible.example.com;
    # ssl_certificate ... (e.g. certbot)

    location / {
        proxy_pass http://127.0.0.1:5505;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
        proxy_buffering off;          # SSE progress stream
        proxy_read_timeout 1h;
    }
}
```
`.env`: `TRUSTED_PROXIES=1`

### Plain HTTP on a trusted LAN

Set `BIND_ADDRESS=0.0.0.0` and `SESSION_COOKIE_SECURE=0`. Do not do this over the internet.

## 3. Configuration reference

| Variable | Default | Meaning |
|---|---|---|
| `SECRET_KEY` | — (required) | Signs sessions. 32+ random bytes recommended. |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | `admin` / generated | First-boot admin only. |
| `SESSION_COOKIE_SECURE` | `1` | Set `0` only for plain-HTTP LAN use. |
| `TRUSTED_PROXIES` | `0` | Number of reverse-proxy hops to trust for `X-Forwarded-*`. |
| `LOG_LEVEL` | `INFO` | `DEBUG`/`INFO`/`WARNING`/`ERROR`. Credential-looking values are masked. |
| `TZ` | `UTC` | Container timezone (scheduler and log timestamps). |
| `BIND_ADDRESS` / `PORT` | `127.0.0.1` / `5505` | Host-side published address (compose). |
| `ABS_URL`, `ABS_API_TOKEN`, `ABS_LIBRARY_ID` | empty | Audiobookshelf integration; set all three or none. See [audiobookshelf.md](audiobookshelf.md). |
| `AUDIBLE_CONFIG_DIR` | `<app>/config` | Override config directory (non-Docker installs). |
| `AUDIBLE_IMAGE` | `ghcr.io/aronjanosch/audible-web-downloader:latest` | Image to run; pin a version tag for production. |

## 4. Logging

Logs go to stderr/stdout (`docker compose logs -f`); compose rotates them (10 MB × 3).
A redaction filter masks token/password/authorization/cookie values and `?token=`-style URL
parameters. Log lines do include Audible **account labels** and book titles (household
labels you chose, at INFO level) but never credentials. Use `LOG_LEVEL=WARNING` to reduce
that further, and mind it when pasting logs into public issues.

## 5. Health check

`GET /healthz` is unauthenticated and returns `{"status":"ok","db":"ok"}` (HTTP 200) or 503.
Compose and the image `HEALTHCHECK` use it. It reveals nothing else.

## 6. Shutdown

`docker compose stop` sends SIGTERM; tini forwards it, gunicorn stops the worker and the
scheduler is shut down. In-flight downloads are not resumable mid-file, but queued/finished
state is persisted and the scheduler re-creates its jobs at next start. The compose file
allows 30 s for graceful stop.

## 7. Backup and restore

What cannot be re-created: `config/` (users, accounts, settings, **Audible tokens**).

```bash
scripts/backup.sh ./config ./backups        # consistent SQLite snapshot + tokens, tar.gz, mode 0600
```

Schedule it (cron / systemd timer) and copy the archive **encrypted, off-host**: it contains
Audible credentials for every member.

Restore:

```bash
docker compose down
mv config config.old
scripts/restore.sh backups/audible-config-YYYYmmdd-HHMMSS.tar.gz ./config
sudo chown -R 1000:1000 config
docker compose up -d
```

Members whose refresh credential was revoked while the backup was old will need to
reconnect from their member page (no admin action required).

## 8. Upgrading

```bash
scripts/backup.sh ./config ./backups
docker compose pull && docker compose up -d
```

Schema migrations are additive and idempotent (`PRAGMA user_version`, currently 5) and run
at startup; existing installs keep their data. Pin `AUDIBLE_IMAGE` to a version tag
(`:1.0.0`) to control when you upgrade. To roll back, restore the pre-upgrade backup and
run the older image (a newer schema is not guaranteed to be readable by an older release).

## 9. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Container exits with `SECRET_KEY is not set` | Set a real `SECRET_KEY` in `.env`. |
| Sign-in page reloads with no error | Plain HTTP with `Secure` cookies. Use HTTPS or set `SESSION_COOKIE_SECURE=0` on a LAN. |
| "Too many attempts" for everyone | `TRUSTED_PROXIES` is `0` behind a proxy; set it to the proxy count. |
| `Permission denied` on `/app/config` | `sudo chown -R 1000:1000 config downloads library library_data`. |
| Progress bar never moves | Proxy buffers SSE; disable buffering for the app. |
| Member sees "Expired" | Amazon revoked the token; the member reconnects from their home page. |
| Books not appearing in Audiobookshelf | Check `ABS_*` variables and that `/app/library` is the folder ABS scans. |
