"""Member-facing view of Audible credential health.

Only non-secret facts are read from auth.json (its mtime and the access token
expiry). Amazon documents refresh tokens as valid until revoked (see
docs/token-lifecycle.md), so there is no honest "expires in N days" figure:
states are healthy, refresh overdue (access token lapsed without renewal), or
expired (rejected/revoked or never connected).
"""

import json
import time

from utils.constants import get_auth_file_path
from utils.events import last_event_time

ACCESS_TOKEN_SECONDS = 3600
OVERDUE_SECONDS = 2 * 3600


def ago(ts, now=None):
    """'3 min ago' style text for a past epoch."""
    if not ts:
        return "never"
    delta = max(0, int((now or time.time()) - ts))
    if delta < 90:
        return "just now"
    if delta < 3600:
        return f"{delta // 60} min ago"
    if delta < 86400:
        return f"{delta // 3600} h ago"
    days = delta // 86400
    return f"{days} day{'s' if days != 1 else ''} ago"


_auth_memo = {}  # (path, mtime_ns) -> (mtime, expires): auth.json is re-read only after it changes


def _read_auth(name):
    path = get_auth_file_path(name)
    try:
        stat = path.stat()
    except OSError:
        return None, None
    key = str(path)
    memo = _auth_memo.get(key)
    if memo and memo[0] == stat.st_mtime_ns:
        return memo[1]
    result = _read_auth_file(path, stat.st_mtime)
    _auth_memo[key] = (stat.st_mtime_ns, result)
    return result


def _read_auth_file(path, mtime):
    expires = None
    try:
        with open(path, encoding="utf-8") as fh:
            value = json.load(fh).get("expires")
        expires = float(value) if value is not None else None
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return mtime, expires


def account_health(name, account, now=None):
    """Return {state, label, percent, detail, needs_attention, since, refreshed}."""
    now = now or time.time()
    refreshed, expires = _read_auth(name)
    if not account.get("authenticated"):
        since = last_event_time(name, "auth_lost")
        if refreshed is None:
            return dict(state="err", label="Not connected", percent=100, refreshed=None, since=None,
                        needs_attention=True,
                        detail="Audible has not been connected yet · automatic downloads are waiting")
        when = f" {ago(since)}" if since else ""
        return dict(state="err", label="Expired", percent=100, refreshed=refreshed, since=since,
                    needs_attention=True,
                    detail=f"Authorization was rejected{when} · auto-download paused until reconnected")
    if expires is not None and now - expires > OVERDUE_SECONDS:
        return dict(state="warn", label="Refresh overdue", percent=12, refreshed=refreshed, since=expires,
                    needs_attention=True,
                    detail=f"Access token lapsed {ago(expires, now)} and was not renewed · last saved {ago(refreshed, now)}")
    remaining = 100
    if expires is not None:
        remaining = max(8, min(100, round((expires - now) / ACCESS_TOKEN_SECONDS * 100)))
    return dict(state="ok", label="Healthy", percent=remaining, refreshed=refreshed, since=None,
                needs_attention=False,
                detail=f"Refreshed {ago(refreshed, now)} · access renews automatically · refresh credential has no fixed expiry")
