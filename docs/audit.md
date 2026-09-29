# v1 evidence audit — in progress (updated 2026-09-29)

The six numbered requirements in `GOAL.md` remain the completion gate. This is
a current-state audit, not a claim that v1 is done.

## PROVEN

- **Safety implementation:** `tests/test_security.py` enumerates private GET and
  mutating routes, checks unauthenticated denial, member scoping, hashed passwords, session expiry,
  login throttling, headers, CSRF, and one-time invite replay. A Node DOM-sink
  test checks escaping of hostile stored text in legacy admin views. The threat mapping is in
  `docs/threat-model.md`. `SECRET_KEY=test-only-key docker compose config --quiet`
  succeeds; the same command without `SECRET_KEY` fails.
- **Token behavior under simulation:** `tests/test_token_lifecycle.py` covers
  expired access, rejected refresh, revoked live request, transient failure,
  and recovery. Provider and library sources are in `docs/token-lifecycle.md`.
- **Audiobookshelf under simulation:** `tests/test_abs_integration.py` uses a
  mocked server for scan, matching, status reconciliation and version/absence
  handling. The integration contract is in `docs/audiobookshelf.md`.
- **Household discovery under simulation:** `tests/test_household_automation.py`
  proves two accounts share one downloaded ASIN but retain separate purchase
  records, purchase metadata survives, failed claims retry, vanished files
  requeue, and disabled downloads still permit polling.
- **Migration and boot:** `tests/test_migration.py` seeds legacy JSON and SQLite,
  checks preservation, stale-claim recovery and idempotency, rejects unreadable legacy JSON, and verifies
  the first-admin handoff. `tests/test_invite_journey.py` follows invite
  registration to a member page and a library API result with external Audible
  OAuth simulated. An isolated source copy booted with 87 routes and one admin.
- **Local gates:** `uv sync --locked --dev`, `uv run --no-sync python -m pytest -q`
  (34 passed), `python -m compileall`, `node --check` for the new ABS settings UI,
  `node --test tests/dom_escaping.test.cjs`, and `git diff --check` passed on 2026-09-28.
- **Browser proxies (item 5):** `scripts/browser/checks.mjs` drives real Chrome against
  `scripts/e2e_server.py` (fake data, external Audible OAuth faked) at 360px: 22/22 checks pass.
  axe-core reports zero critical or serious violations on invite landing, login, member library
  and admin `/`, `/settings`, `/downloads`, `/import`; no horizontal scroll at 360px on any of them;
  keyboard-only onboarding (skip link, Tab order, visible focus, Enter submit) reaches the OAuth step;
  invite link -> registration -> member sign-in -> own book visible works end to end; no failed
  requests or page errors. Bugs found and fixed by this run: unnamed select/links, focusable
  content in `aria-hidden`, dark-theme contrast, invalid `pattern` regex, admin-only SSE/API calls
  from invite and member pages. Screenshots land in `scripts/browser/out/` (gitignored).
- **Audiobookshelf against a real server:** `scripts/abs_live_check.py` ran on 2026-09-29 against
  a real Audiobookshelf 2.37.0 (run from source, fake m4b, throwaway user; seedhost runs 2.36.1, so
  this also covers a version difference). Scan accepted, item listed with its ASIN, reconciliation
  produced `matched` (asin) and `pending`, and a wrong token (HTTP 401) or an unreachable server raised
  `AudiobookshelfError` with stored state unchanged. Output: `LIVE ABS CHECK PASSED`.
- **Test isolation:** plain `uv run pytest` (34 passed) no longer depends on cwd or on the
  developer's real `config/` (`AUDIBLE_CONFIG_DIR`, `tests/conftest.py`).
- **Hosted CI and image:** The `test` and `image` jobs in
  `.github/workflows/ci.yml` passed on 2026-09-28. The image job published to
  GHCR and booted the image as UID 1000 before checking `/login`.

## IMPROVED BUT APPROXIMATE

- **Experience:** Members have a focused responsive library page, reconnect action,
  skip link, visible keyboard focus, and named buttons before JavaScript runs.
  These are implementation checks, not a browser accessibility pass or visual proof.
- **Performance proxy:** `scripts/benchmark.py` measured baseline and current
  local Flask response times against an empty install. Both meet the p95 budget
  in `docs/performance.md`; network and browser rendering are excluded.
- **Invite journey:** The automated test crosses HTTP route boundaries and sees
  an owned library result, but does not run browser JavaScript or real Audible OAuth.
- **Threat model:** Tests support listed mitigations. Its deployment assumptions
  (TLS proxy, private config volume, patched host) cannot be verified here.

## STILL OPEN

- Live expired/revoked Audible credential and member reconnect exercise. Needs a real member's
  Audible login and a token that actually expires or is revoked; not run because it would process
  real people's account data. To unlock: a member re-authenticates via the app's reconnect action
  on a disposable/consented account and the outcome is observed.
- Same live ABS check against the household's own server (seedhost): needs `ABS_API_TOKEN` and
  `ABS_LIBRARY_ID` in its private `.env`.
- Visual refinement of the admin interface: it passes the proxies above but still uses the older
  Bootstrap structure. Moderate/minor axe findings remain (1-2 per page). Bootstrap/Font Awesome
  load from CDNs.
