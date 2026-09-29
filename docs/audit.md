# v1 evidence audit — in progress

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

- Browser accessibility run with zero critical violations, keyboard-only onboarding
  walkthrough, and visual check at 360px. The computer-use browser inventory was
  empty (`browsers: []`); opening the in-app browser returned “Browser is not
  available: iab.”
- Full browser end-to-end test from invite link through rendering the library.
- Live expired/revoked Audible credential and member reconnect exercise.
- Authenticated Audiobookshelf scan and reconciliation against a live server.
- Visual refinement of the admin interface and browser verification of its phone
  layout. The existing admin interface still uses the older Bootstrap structure.
