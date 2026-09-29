"""Audible device credential maintenance.

An access token is short lived; the device refresh token is retained in auth.json.
Never delete that file on an API failure: a member can reauthorize in place.
"""

import os
import tempfile
from pathlib import Path
from threading import Lock

import audible
import httpx
from audible.exceptions import Unauthorized

from utils.constants import get_auth_file_path
from utils.errors import AuthenticationError


_locks_guard = Lock()
_locks = {}


def _account_lock(account_name):
    with _locks_guard:
        return _locks.setdefault(account_name, Lock())


def _set_authenticated(account_name, value):
    from utils.config_manager import get_config_manager

    manager = get_config_manager()
    account = manager.get_account(account_name)
    if account is not None and account.get("authenticated") != value:
        manager.update_account(account_name, {"authenticated": value})
        from utils.events import record_event
        record_event(account_name, "auth_restored" if value else "auth_lost")


def _save_auth(auth, path: Path):
    """Replace credentials atomically, with mode 0600 and no partial JSON writes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".auth-", suffix=".json", dir=path.parent)
    os.close(fd)
    try:
        auth.to_file(Path(temp_name), encryption=False)
        os.chmod(temp_name, 0o600)
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def save_authenticator(account_name, auth):
    """Persist fresh credentials after login or refresh."""
    with _account_lock(account_name):
        _save_auth(auth, get_auth_file_path(account_name))
        _set_authenticated(account_name, True)


def is_auth_rejection(error):
    """Only credential rejection should change the account's auth state."""
    if isinstance(error, Unauthorized):
        return True
    if isinstance(error, httpx.HTTPStatusError):
        if error.response.status_code in (401, 403):
            return True
        if error.response.status_code == 400:
            try:
                return error.response.json().get('error') == 'invalid_grant'
            except (ValueError, AttributeError):
                return False
    return False


def mark_auth_rejected(account_name, error):
    if is_auth_rejection(error):
        _set_authenticated(account_name, False)
        return True
    return False


def load_authenticator(account_name):
    """Load credentials and persist a renewed access token when due.

    Network failures leave auth state unchanged. A rejected refresh marks the
    account for member reauthorization while retaining the old file for recovery.
    """
    path = get_auth_file_path(account_name)
    with _account_lock(account_name):
        if not path.exists():
            _set_authenticated(account_name, False)
            raise AuthenticationError("Audible account needs authentication")
        try:
            auth = audible.Authenticator.from_file(path)
        except (ValueError, TypeError, OSError, KeyError) as error:
            _set_authenticated(account_name, False)
            raise AuthenticationError("Audible credentials are unreadable") from error

        if (getattr(auth, "access_token", None)
                and getattr(auth, "expires", None) is not None
                and auth.access_token_expired):
            if not getattr(auth, "refresh_token", None):
                _set_authenticated(account_name, False)
                raise AuthenticationError("Audible account needs reauthentication")
            try:
                auth.refresh_access_token()
            except Exception as error:
                if mark_auth_rejected(account_name, error):
                    raise AuthenticationError("Audible authorization expired or was revoked") from error
                raise
            _save_auth(auth, path)
        return auth


async def probe_authenticator(account_name):
    """Ask Audible for a small library page to catch revocation of signed devices."""
    auth = load_authenticator(account_name)
    try:
        async with audible.AsyncClient(auth=auth) as client:
            await client.library(num_results=1)
    except Exception as error:
        if mark_auth_rejected(account_name, error):
            raise AuthenticationError("Audible authorization expired or was revoked") from error
        raise
    _set_authenticated(account_name, True)
    return auth
