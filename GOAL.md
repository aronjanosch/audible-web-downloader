# GOAL.md — v1 product goal

This is the long-form brief behind the Codex `/goal`. Paste the `/goal` block below into
Codex from the repository root. The `Definition of Done (v1)` is the finish line.

## Context

An older, hand-built Flask app that lets a household share their Audible libraries: family
and friends self-serve their own account via an invite, authenticate themselves, and the app
downloads, decrypts and organizes their books into a shared Audiobookshelf/Plex library.

Goal: take it from a working side project to a modern, beautiful and trustworthy product a
family could safely self-host on the open internet — keeping its soul, losing the rough edges.
The *how* is open: adopt a frontend framework, redesign the architecture, restructure freely,
add capabilities — provided it stays a single, self-hosted, simple-to-deploy app.

## What "great" must include

- **Safe to expose publicly** — real per-user accounts and roles; each member manages only
  their own Audible account, an admin oversees the household.
- **Deep Audiobookshelf integration**, and clean integration with other library/notification
  targets where it makes sense.
- **Long-lived Audible tokens** — keep every member's token alive as long as technically
  possible, detect expiry/revocation automatically, and let members re-authenticate themselves
  without the admin.
- **Household automation** — new purchases by *any* linked account are pulled in automatically,
  with cross-account dedupe and clear attribution.
- **Beautiful but minimal** — modern, intuitive, responsive, delightful on a phone, no bloat
  or gimmicks.

## Definition of Done (v1)

The goal is complete **only when all of these are true and evidenced**. Each numbered item is a
required feature, not a suggestion.

1. **Safety.** Per-user accounts and roles (members see/manage only their own Audible account;
   admin oversees). Passwords hashed, sessions expire, login rate-limited, security headers set.
   Every mutating/admin route returns 401/403 unauthenticated — asserted per-route in tests. A
   written threat model maps each realistic threat → mitigation → proving test/command, with no
   unresolved high/critical findings.

2. **Token lifecycle.** Determine and document the maximum token lifetime achievable against the
   current Audible API, with sources. Implement automatic refresh wherever the API permits; detect
   expired/revoked tokens automatically; provide a member self-service re-auth flow needing no
   admin. Prove detection + recovery with a test simulating an expired/revoked token.

3. **Audiobookshelf integration.** Deep and documented (scan trigger, ASIN/title matching, status
   sync, sensible behavior when ABS is absent or a version differs), with automated tests against
   a mocked ABS.

4. **Household automation.** New purchases by any linked account are detected and auto-queued,
   with cross-account deduplication and clear per-account attribution. Proven by an automated test.

5. **Experience.** Modern, minimal, functional, genuinely pleasant — responsive, delightful on a
   phone, obvious to a first-time user. "Beautiful" is not directly auditable, so verify with
   **proxies, labeled as proxies**: accessibility run with zero critical violations, a keyboard-only
   onboarding walkthrough, a measured performance budget (page + API latency, before/after), correct
   rendering at 360px, and an end-to-end test from invite link to seeing one's library.

6. **No regression.** Clean checkout boots; full test suite and CI pass. A test seeds a legacy
   install (old JSON config + existing SQLite schema) and asserts a forward migration with zero
   data loss and idempotency. New tests cover behavior that changed.

Finish with an audit separating **PROVEN** (naming the command/test/measurement), **IMPROVED BUT
APPROXIMATE**, and **STILL OPEN**.

## Constraints

- Never break or lock out existing users; never silently lose their data.
- Don't weaken what the app already does.
- Keep it a private tool for books people own for their own household — never redistribution or a
  public piracy service.
- Stay self-hosted and reasonably lightweight.
- Do not trade correctness for polish.

## Boundaries

- This repository and its dependencies; the Audible, Audiobookshelf and related integrations already
  present; the network and library endpoints available to you.
- You may add frameworks, libraries and subagents.

## Iteration policy

- Keep a living plan and a short decision log a human can absorb in minutes.
- Work in small, safe, reviewable changes; after each, run the tests and verify the result yourself,
  then pick the next highest-value action.
- When ambition and safety conflict, protect the running app and the data first, then keep improving.
- Complete only when the Definition of Done is met and proven — never on belief.

## If blocked

A credential you can't obtain, an external API that refuses, a verification that can't run — stop and
report the attempted paths, the evidence gathered, the specific blocker, and what would unlock progress.

## The `/goal` to paste into Codex

```text
/goal Turn this old Audible household-library web app into a modern, trustworthy product a family could safely self-host on the open internet — keeping its soul (invite-based, multi-account Audible liberation of people's own purchases) while making it feel like something built today. You may adopt a frontend framework, redesign the architecture, restructure freely, and add capabilities, as long as it stays a single self-hosted, simple-to-deploy app. The v1 Definition of Done in GOAL.md is the finish line — read GOAL.md and treat its numbered items as the required features and its audit format as the reporting standard.

Verification surface: every DoD item must be backed by concrete evidence — a test, command, measurement or written artifact — not assertion. End with an audit separating PROVEN (with the proving evidence), IMPROVED BUT APPROXIMATE, and STILL OPEN.

Constraints: never break or lock out existing users; never silently lose their data; don't weaken what the app already does; keep it a private tool for books people own for their own household — never redistribution or a public piracy service; stay self-hosted and reasonably lightweight; do not trade correctness for polish.

Boundaries: this repository and its dependencies; the Audible, Audiobookshelf and related integrations already present; the network and library endpoints available to you. You may add frameworks, libraries and subagents.

Iteration policy: keep a living plan and a short decision log a human can absorb in minutes; work in small, safe, reviewable changes; after each, run the tests and verify the result yourself, then pick the next highest-value action; when ambition and safety conflict, protect the running app and the data first, then keep improving. Complete only when the Definition of Done is met and proven, never on belief.

If blocked — a credential you can't obtain, an external API that refuses, a verification that can't run — stop and report the attempted paths, the evidence gathered, the specific blocker, and what would unlock progress.
```
