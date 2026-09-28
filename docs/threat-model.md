# v1 threat model

Scope: a household app reachable through an HTTPS reverse proxy, with one
Gunicorn worker, a private `config/` volume, and invited members. The owner
keeps the host, reverse proxy, and backups patched and private.

| Threat | Mitigation | Proving test or command | Residual risk |
| --- | --- | --- | --- |
| Unauthenticated visitor reads or changes settings, downloads, libraries, or account links | Central authorization runs before handlers; shared operations require admin | `uv run python -m pytest -q tests/test_security.py::test_every_private_route_rejects_unauthenticated` enumerates every registered private GET and mutation | Invitation endpoints deliberately accept an invite token as authorization; invalid tokens return 403 |
| One member reads or changes another member's Audible account | Users have a unique account binding; central guard and route checks enforce account ownership; aggregate account/library views are filtered | `tests/test_security.py::test_member_only_sees_owned_account` | Shared downloaded library and import controls remain admin-only |
| Password database theft exposes plain passwords | Werkzeug adaptive password hashes; no password in session or response | `tests/test_security.py::test_session_expires_and_password_is_hashed` | A stolen database still exposes metadata and may permit offline guesses against weak member passwords; 12-character minimum |
| Stolen browser session stays valid indefinitely | Signed, HttpOnly, SameSite=Lax, Secure cookies; absolute 12-hour session expiry | `tests/test_security.py::test_session_expires_and_password_is_hashed`; inspect `utils/security.py` cookie settings | A stolen active cookie can be used until expiry; TLS and private devices remain necessary |
| Password guessing | Five failed logins per remote address per 15 minutes; generic failure response | `tests/test_security.py::test_login_limit_and_security_headers` | Limiter is in memory and resets on restart. A reverse proxy should also limit abusive traffic |
| Login return URL sends a member to an attacker site | Only local path redirects are accepted; protocol-relative and backslash forms are rejected | `tests/test_security.py::test_login_next_rejects_external_redirect_shapes` | Keep deployment proxy URL rewriting conservative |
| Session forgery via a known signing key | Compose requires an explicit `SECRET_KEY`; local missing key is randomly generated, and docs require a long random value | `docker compose config` fails when `SECRET_KEY` is unset; inspect `docker-compose.yml` | Protect the deployment environment and backups |
| Upgraded household cannot sign in because no admin password exists | First boot creates an admin and writes a random one-time password to a mode 0600 file in the private config volume | `tests/test_migration.py::test_upgrade_bootstraps_retrievable_admin_without_touching_accounts` | The host owner must read and remove the credentials file after setup; a compromised config volume exposes it |
| CSRF on a signed-in browser | Flask-WTF CSRF check on every private mutation and invitation registration; one-time OAuth flow IDs for callback endpoints | `tests/test_security.py` sends CSRF tokens for authenticated mutations; remove a token and observe 400 | Browser extensions or XSS can bypass CSRF, so template escaping and updates matter |
| Clickjacking, MIME confusion, excess browser permissions | `frame-ancestors 'none'`, `X-Frame-Options`, `nosniff`, Permissions-Policy, and `no-store` on auth/API responses | `tests/test_security.py::test_login_limit_and_security_headers` | CSP permits the legacy inline scripts and external styles; strict script CSP needs frontend refactoring |
| Stored account, book, path, or provider error text executes in the admin browser | Dynamic HTML sinks escape text and attribute values or assign through `textContent`; toast and OAuth status messages are text nodes | `node --test tests/dom_escaping.test.cjs` exercises hostile values in the settings, download, import, and toast renderers | Browser-based CSP and accessibility verification remains open |
| Leaked invitation link permits claiming a member account | 32-byte random account tokens and separately validated household invite token; account-specific claim creates one user and revokes link | `tests/test_security.py::test_account_invite_is_revoked_after_claim` checks one-time claim and replay; `tests/test_invite_journey.py` covers registration | The reusable household invite remains a bearer credential; revoke it after sharing or if leaked |
| Audible token theft from disk or logs | Auth files remain under ignored `config/`; API endpoints require household authorization; `Cache-Control: no-store` on auth responses | `git check-ignore config/auth/example/auth.json`; route authorization test | Host compromise or exposed backup can still leak Audible tokens |

No known unresolved high or critical application finding remains under the
deployment assumptions above. The app must be served over HTTPS with a secret
signing key and a private state volume. The process-local login limiter and
legacy script CSP are defense-in-depth limitations to revisit before a larger
public deployment.
