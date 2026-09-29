# v1 working plan and decision log

Status: in progress. The finish line is the six numbered items in `GOAL.md`.

| Area | Current evidence | Next proof |
| --- | --- | --- |
| Safety | Per-user roles, central guard, first-admin handoff, security route tests, threat model | Recheck every route after final edits |
| Token lifecycle | Refresh/revocation service and simulated tests | Live Audible account exercise when credentials are available |
| Audiobookshelf | Scan, reconciliation, documented matching, mock tests | Live server/version smoke test when available |
| Household automation | Every linked account is polled; durable account purchases, atomic claims and shared-purchase test | Live purchase poll when credentials are available |
| Experience | Member library page, accessible skip link, invite-to-library server journey, measured latency | Browser accessibility run, keyboard and 360px checks, full browser E2E |
| No regression | Fresh JSON and existing v3 SQLite migration tests, stale-claim recovery, isolated clean-copy boot and local suite | Hosted CI result |

## Decisions

- Keep Flask and one Gunicorn worker for v1. The queue is process-local; increasing workers would split state.
- Keep old JSON files and Audible credentials in place during migration; add SQLite tables for identity, attribution and ABS status.
- One library copy is keyed by ASIN. Every Audible account that lists an ASIN gets its own ownership row.
- Disabled automatic downloads still permit purchase discovery. A failed download claim returns to `wanted` for retry.
- Polling checks downloaded paths that an account owns and requeues vanished files; purchase metadata is retained for routing and display.
- Audiobookshelf remains optional; its downtime cannot block owned-book downloads.
- A fresh or upgraded installation creates a random first-admin credential in a private mode 0600 config file if no admin password was configured. This keeps old installs reachable while requiring household login.
