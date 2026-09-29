"""Household authorization checks, including every registered private mutation."""

import time
import re

import pytest


@pytest.fixture
def household(tmp_path, monkeypatch):
    import utils.constants as constants
    import utils.db as db
    import utils.scheduler as scheduler
    old = getattr(db._local, "conn", None)
    if old is not None:
        old.close()
        db._local.conn = None
    monkeypatch.setattr(constants, "DB_FILE", tmp_path / "audible.db")
    monkeypatch.setattr(scheduler, "init_scheduler", lambda app: None)
    monkeypatch.setenv("SECRET_KEY", "test-only-secret")
    monkeypatch.setenv("ADMIN_PASSWORD", "admin-password-123")
    from app import create_app
    app = create_app()
    app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
    conn = db.get_db()
    conn.execute("INSERT INTO accounts (name,region) VALUES ('alice','us'),('bob','us')")
    conn.commit()
    from utils.security import create_user
    admin = dict(conn.execute("SELECT id,username,role,account_name FROM users WHERE role='admin'").fetchone())
    alice = create_user("alice", "alice-password-123", "member", "alice")
    yield app, app.test_client(), admin, alice
    db._local.conn.close()
    db._local.conn = None


def _signed_in(client, user):
    with client.session_transaction() as sess:
        sess["user_id"] = user["id"]
        sess["login_at"] = time.time()


def _csrf(client):
    page = client.get("/login").get_data(as_text=True)
    token = re.search(r'name="csrf-token" content="([^"]+)"', page).group(1)
    return {"X-CSRFToken": token}


def _path(rule):
    path = rule.rule
    for argument in rule.arguments:
        replacement = "alice" if "account" in argument else "x"
        if argument == "asin":
            replacement = "B000TEST"
        path = path.replace(f"<{argument}>", replacement)
        path = path.replace(f"<path:{argument}>", replacement)
    return path


def test_every_private_route_rejects_unauthenticated(household):
    app, client, _, _ = household
    checked = []
    csrf_headers = _csrf(client)
    for rule in app.url_map.iter_rules():
        if rule.endpoint in {"static", "security.login", "security.login_page"}:
            continue
        for method in sorted(rule.methods & {"GET", "POST", "PUT", "PATCH", "DELETE"}):
            response = client.open(_path(rule), method=method, headers=csrf_headers)
            assert response.status_code in {401, 403}, (rule.endpoint, method, response.status_code)
            checked.append((rule.endpoint, method))
    assert len(checked) >= 20


def test_member_only_sees_owned_account(household):
    _, client, _, alice = household
    _signed_in(client, alice)
    response = client.get("/api/accounts")
    assert response.status_code == 200
    assert set(response.json) == {"alice"}
    assert client.get("/api/library/all").status_code == 200
    headers = _csrf(client)
    assert client.post("/api/library/fetch", json={"account_name": "bob"}, headers=headers).status_code == 403
    assert client.put("/api/accounts/bob/auto-download", json={}, headers=headers).status_code == 403
    assert client.get("/settings").status_code == 403


def test_every_admin_route_rejects_member(household):
    app, client, _, alice = household
    _signed_in(client, alice)
    headers = _csrf(client)
    allowed = {
        "main.index", "main.get_session_state", "main.get_accounts", "main.select_account",
        "auth.start_login", "auth.login_page", "auth.login_callback", "auth.login_status",
        "auth.check_auth", "auth.authenticate", "auth.fetch_library_route", "auth.fetch_all_libraries",
        "scheduler.get_auto_download_status", "scheduler.configure_auto_download",
        "scheduler.trigger_auto_download", "security.logout",
    }
    checked = []
    for rule in app.url_map.iter_rules():
        if rule.endpoint in allowed or rule.endpoint == "static" or rule.endpoint.startswith(("security.", "invite.")):
            continue
        method = next((m for m in ("POST", "PUT", "PATCH", "DELETE", "GET") if m in rule.methods), None)
        if method:
            response = client.open(_path(rule), method=method, headers=headers)
            assert response.status_code == 403, (rule.endpoint, method, response.status_code)
            checked.append(rule.endpoint)
    assert len(checked) >= 20


def test_session_expires_and_password_is_hashed(household):
    _, client, _, alice = household
    from utils.db import get_db
    from utils.security import SESSION_SECONDS
    row = get_db().execute("SELECT password_hash FROM users WHERE id=?", (alice["id"],)).fetchone()
    assert "alice-password-123" not in row["password_hash"]
    with client.session_transaction() as sess:
        sess["user_id"] = alice["id"]
        sess["login_at"] = time.time() - SESSION_SECONDS - 1
    assert client.get("/api/accounts").status_code == 401


def test_login_limit_and_security_headers(household):
    _, client, _, _ = household
    headers = _csrf(client)
    for _ in range(5):
        response = client.post("/login", json={"username": "admin", "password": "wrong"}, headers=headers)
        assert response.status_code == 401
    assert client.post("/login", json={"username": "admin", "password": "admin-password-123"}, headers=headers).status_code == 429
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors" in response.headers["Content-Security-Policy"]


def test_valid_login_logout_and_csrf(household):
    _, client, _, _ = household
    assert client.post("/login", json={"username": "admin", "password": "admin-password-123"}).status_code == 400
    headers = _csrf(client)
    response = client.post("/login", json={"username": "admin", "password": "admin-password-123"}, headers=headers)
    assert response.status_code == 200
    assert response.json["role"] == "admin"
    assert client.get("/api/accounts").status_code == 200
    assert client.post("/logout").status_code == 400
    headers = _csrf(client)
    assert client.post("/logout", headers=headers).status_code == 302
    assert client.get("/api/accounts").status_code == 401


def test_login_next_rejects_external_redirect_shapes(household):
    _, client, _, _ = household
    headers = _csrf(client)
    for destination in ('//evil.example', '/\\evil.example', 'https://evil.example'):
        response = client.post('/login', json={
            'username': 'admin', 'password': 'admin-password-123', 'next': destination,
        }, headers=headers)
        assert response.status_code == 200
        assert response.json['redirect'] == '/'
        headers = _csrf(client)


def test_invite_creates_scoped_member_login(household, monkeypatch):
    _, client, _, _ = household
    monkeypatch.setattr("routes.invite.settings_manager.validate_invitation_token", lambda token: token == "valid-invite")
    payload = {"account_name": "charlie", "region": "us", "username": "charlie", "password": "charlie-password-123"}
    assert client.post("/invite/valid-invite/add-account", json=payload).status_code == 400
    headers = _csrf(client)
    response = client.post(
        "/invite/valid-invite/add-account",
        json=payload,
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json["auth_url"].endswith("/charlie")
    assert set(client.get("/api/accounts").json) == {"charlie"}
    assert client.get("/auth/login/bob").status_code == 403
    assert client.post("/invite/bad-invite/add-account", json={}, headers=_csrf(client)).status_code == 403


def test_account_invite_is_revoked_after_claim(household):
    _, client, _, _ = household
    from utils.config_manager import get_config_manager

    get_config_manager().update_account('bob', {'pending_invitation_token': 'one-time-token'})
    assert client.get('/invite/account/one-time-token').status_code == 200
    response = client.post('/invite/account/one-time-token/claim', json={
        'username': 'bob', 'password': 'bob-password-123',
    }, headers=_csrf(client))
    assert response.status_code == 200
    assert set(client.get('/api/accounts').json) == {'bob'}
    assert client.get('/invite/account/one-time-token').status_code == 403
    assert client.post('/invite/account/one-time-token/claim', json={
        'username': 'another', 'password': 'another-password-123',
    }, headers=_csrf(client)).status_code == 403
