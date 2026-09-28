# Household purchase discovery

Each authenticated Audible account receives an interval job (default six hours).
The job fetches the account's purchases and records every ASIN in `account_books`.
The first sighting also creates a `wanted` book row. If two accounts own the same
ASIN, both ownership rows remain, while the shared library uses one book row and
one download. The unified catalog API returns `account_names` for attribution;
the admin cards and list show all owners.

New accounts have automatic downloads enabled. Ordered account rules choose a
destination library; otherwise a configured default is used. If there is exactly
one library, it is the fallback. With multiple libraries and no rule or default,
purchases stay `wanted` until a destination is configured. Turning automatic
downloads off still discovers and records purchases, but does not start a download.

Before a download starts, the job atomically changes the ASIN from `wanted` or
`missing` to `downloading` in SQLite. Another account's concurrent job cannot
claim it. A successful path marks it `downloaded`; failure returns it to `wanted`
for the next poll. Startup migration also returns stale `downloading` rows to
`wanted` after a process restart. Each poll checks whether downloaded files for
that account still exist; vanished files become `missing` and can be claimed
again. Existing decrypted files are not removed.

`tests/test_household_automation.py` simulates two accounts sharing an ASIN,
checks attribution, one copy and retry, verifies polling when downloads are off,
checks recovery of a vanished file, and checks the unified API owner list.
