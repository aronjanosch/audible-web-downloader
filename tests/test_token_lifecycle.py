"""Credential expiry, revocation and member-driven recovery without Audible network."""

import asyncio
import time

import httpx
import pytest

from utils import token_lifecycle as tokens
from utils.errors import AuthenticationError


class FakeConfig:
    def __init__(self):
        self.accounts = {'alice': {'region': 'us', 'authenticated': True}}

    def get_accounts(self):
        return {name: data.copy() for name, data in self.accounts.items()}

    def get_account(self, name):
        return self.accounts.get(name, {}).copy() or None

    def update_account(self, name, updates):
        self.accounts[name].update(updates)

    def save_accounts(self, accounts):
        self.accounts = accounts


class FakeAuth:
    def __init__(self, expired=False, refresh_error=None):
        self.access_token = 'access-secret'
        self.expires = 1
        self.access_token_expired = expired
        self.refresh_token = 'refresh-secret'
        self.refresh_error = refresh_error
        self.refreshed = False

    def refresh_access_token(self):
        if self.refresh_error:
            raise self.refresh_error
        self.refreshed = True
        self.access_token_expired = False

    def to_file(self, path, encryption=False):
        path.write_text('refreshed' if self.refreshed else 'reconnected')


@pytest.fixture
def setup_token(monkeypatch, tmp_path):
    config = FakeConfig()
    path = tmp_path / 'auth.json'
    path.write_text('old')
    monkeypatch.setattr(tokens, 'get_auth_file_path', lambda name: path)
    monkeypatch.setattr('utils.config_manager.get_config_manager', lambda: config)
    return config, path


def rejected_status(code):
    request = httpx.Request('POST', 'https://api.amazon.com/auth/token')
    response = httpx.Response(code, request=request)
    return httpx.HTTPStatusError('rejected', request=request, response=response)


def test_expired_token_refreshes_and_persists(monkeypatch, setup_token):
    config, path = setup_token
    auth = FakeAuth(expired=True)
    monkeypatch.setattr(tokens.audible.Authenticator, 'from_file', lambda _: auth)

    assert tokens.load_authenticator('alice') is auth
    assert path.read_text() == 'refreshed'
    assert path.stat().st_mode & 0o777 == 0o600
    assert config.accounts['alice']['authenticated'] is True


def test_revoked_refresh_detected_then_member_reconnects(monkeypatch, setup_token):
    config, path = setup_token
    rejected = FakeAuth(expired=True, refresh_error=rejected_status(401))
    monkeypatch.setattr(tokens.audible.Authenticator, 'from_file', lambda _: rejected)

    with pytest.raises(AuthenticationError):
        tokens.load_authenticator('alice')
    assert config.accounts['alice']['authenticated'] is False
    assert path.read_text() == 'old'  # never destroy recoverable credential state

    tokens.save_authenticator('alice', FakeAuth())
    assert config.accounts['alice']['authenticated'] is True
    assert path.read_text() == 'reconnected'


def test_api_rejection_detected_even_with_unexpired_token(monkeypatch, setup_token):
    config, _ = setup_token
    monkeypatch.setattr(tokens.audible.Authenticator, 'from_file', lambda _: FakeAuth())

    class Client:
        def __init__(self, auth):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def library(self, **kwargs):
            raise rejected_status(403)

    monkeypatch.setattr(tokens.audible, 'AsyncClient', Client)
    with pytest.raises(AuthenticationError):
        asyncio.run(tokens.probe_authenticator('alice'))
    assert config.accounts['alice']['authenticated'] is False


def test_transient_failure_does_not_mark_account_revoked(monkeypatch, setup_token):
    config, _ = setup_token
    auth = FakeAuth(expired=True, refresh_error=httpx.ConnectError('offline'))
    monkeypatch.setattr(tokens.audible.Authenticator, 'from_file', lambda _: auth)
    with pytest.raises(httpx.ConnectError):
        tokens.load_authenticator('alice')
    assert config.accounts['alice']['authenticated'] is True


def test_member_can_start_own_reauthentication_after_rejection(tmp_path, monkeypatch):
    import utils.constants as constants
    import utils.db as db
    import utils.scheduler as scheduler
    old = getattr(db._local, 'conn', None)
    if old is not None:
        old.close()
        db._local.conn = None
    monkeypatch.setattr(constants, 'DB_FILE', tmp_path / 'audible.db')
    monkeypatch.setattr(scheduler, 'init_scheduler', lambda app: None)
    monkeypatch.setenv('SECRET_KEY', 'test-only-secret')
    monkeypatch.setenv('ADMIN_PASSWORD', 'admin-password-123')
    from app import create_app
    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SESSION_COOKIE_SECURE=False)
    db.get_db().execute("INSERT INTO accounts (name,region,authenticated) VALUES ('alice','us',0),('bob','us',0)")
    db.get_db().commit()
    from utils.security import create_user
    member = create_user('alice', 'alice-password-123', 'member', 'alice')
    client = app.test_client()
    with client.session_transaction() as session:
        session['user_id'] = member['id']
        session['login_at'] = time.time()

    monkeypatch.setattr('routes.auth.start_oauth_login', lambda **kwargs: 'test-session')
    assert client.get('/auth/login/alice').status_code == 302
    assert client.get('/auth/login/bob').status_code == 403
    db._local.conn.close()
    db._local.conn = None
