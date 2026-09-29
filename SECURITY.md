# Security policy

## Reporting a vulnerability

Please report privately via GitHub: **Security → Report a vulnerability** on this repository
(private security advisory). Do not open a public issue. Include the version, a description,
and reproduction steps. Expect an acknowledgement within a few days.

Never include real Audible tokens, `config/` contents, or unredacted logs in a report.

## Supported versions

Only the latest release and `edge` receive fixes.

## Security model (summary)

- Per-user accounts (admin / member) with hashed passwords, 12-hour sessions, CSRF protection,
  login rate limiting (per client IP — set `TRUSTED_PROXIES` correctly behind a proxy), and
  security headers. Members can act only on their own Audible account.
- Audible tokens are stored on the server in `config/auth/<account>/auth.json` (mode 0600).
  Your Amazon password never reaches this app. Treat `config/` as a secret and back it up encrypted.
- The app refuses to start in production without a real `SECRET_KEY`.
- Run it behind HTTPS. The container runs as a non-root user and supports a read-only root filesystem.

The full threat model with mitigations and tests is in [docs/threat-model.md](docs/threat-model.md).
Operational guidance is in [docs/deployment.md](docs/deployment.md).

## Scope

This tool is for backing up audiobooks you have purchased, for your own household. It must not be
extended to redistribute decrypted content.
