# Audible credential lifetime and recovery

Checked 2026-09-28 against the installed `audible` 0.10.0 implementation, current
upstream `audible` 0.12 documentation, and Amazon's Login with Amazon documentation.
Audible uses a non-public API, so Amazon's LWA
documentation is the closest provider statement rather than a contractual
guarantee for every Audible device credential.

## Maximum achievable lifetime

- An Audible access token lasts **60 minutes** and can be renewed with the device
  refresh token. [Audible authentication documentation](https://audible.readthedocs.io/en/latest/auth/authentication.html)
  and [Amazon's access-token documentation](https://developer.amazon.com/docs/login-with-amazon/access-token.html).
- Amazon describes refresh tokens as **valid indefinitely unless the customer
  removes the app's authorization**. It gives no fixed maximum lifetime in days.
  Thus the documented upper bound is conditional and unbounded; this application
  cannot promise that a particular Audible credential will last forever.
  [Amazon refresh-token documentation](https://developer.amazon.com/docs/login-with-amazon/refresh-token.html).
- The `audible` library's `Authenticator.refresh_access_token()` uses the stored
  refresh token, updates the access token and expiry, and its client automatically
  refreshes bearer requests. Signing is preferred when device signing credentials
  exist. This app explicitly refreshes expired access tokens and writes the result
  back to disk because a refresh done only in memory is lost on restart.
  [Audible authenticator source](https://audible.readthedocs.io/en/latest/_modules/audible/auth.html).

## App behavior

1. On account use, `utils.token_lifecycle.load_authenticator` refreshes an expired
   access token. It writes `auth.json` atomically with mode `0600`.
2. The explicit auth check and scheduled library checks make a small Audible
   request. A 401/403 from Audible, or a rejected refresh, sets the account's
   `authenticated` flag to false. Network outages and server faults leave the
   flag unchanged. The auth file is retained for diagnosis and recovery.
3. The member logs into the household app, opens their own Audible connect flow,
   and completes Amazon authentication. Fresh credentials replace the old file and
   mark the account authenticated. An admin can oversee accounts but need not
   handle a member's Audible credentials.

This is tested without a live Amazon login by
`tests/test_token_lifecycle.py`: expiry refresh, revoked refresh, recovery, API
rejection of an unexpired token, and a transient network failure.
