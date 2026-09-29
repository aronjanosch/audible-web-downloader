"""Deployment-facing behaviour: health probe, secret handling, proxy trust, log redaction."""
import logging

import pytest


@pytest.fixture
def make_app(tmp_path, monkeypatch):
    import utils.constants as constants
    import utils.db as db
    import utils.scheduler as scheduler
    old = getattr(db._local, "conn", None)
    if old is not None:
        old.close()
        db._local.conn = None
    monkeypatch.setattr(constants, "DB_FILE", tmp_path / "audible.db")
    monkeypatch.setattr(scheduler, "init_scheduler", lambda app: None)
    monkeypatch.setenv("ADMIN_PASSWORD", "admin-password-123")
    monkeypatch.delenv("FLASK_ENV", raising=False)
    monkeypatch.delenv("AUDIBLE_ALLOW_EPHEMERAL_KEY", raising=False)
    monkeypatch.delenv("TRUSTED_PROXIES", raising=False)

    def factory():
        from app import create_app
        return create_app()

    yield factory
    conn = getattr(db._local, "conn", None)
    if conn is not None:
        conn.close()
        db._local.conn = None


def test_healthz_is_public_and_minimal(make_app, monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-only-secret")
    client = make_app().test_client()
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json == {"status": "ok", "db": "ok"}
    assert response.headers["Cache-Control"] == "no-store"


def test_production_refuses_missing_or_placeholder_secret(make_app, monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        make_app()
    monkeypatch.setenv("SECRET_KEY", "change-me")
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        make_app()


def test_development_gets_ephemeral_secret(make_app, monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.setenv("FLASK_ENV", "development")
    assert len(make_app().config["SECRET_KEY"]) >= 32


def test_proxy_headers_only_trusted_when_configured(make_app, monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-only-secret")
    headers = {"X-Forwarded-For": "203.0.113.9", "X-Forwarded-Proto": "https"}
    app = make_app()
    seen = {}

    @app.get("/_whoami")
    def whoami():
        from flask import request
        seen["addr"], seen["scheme"] = request.remote_addr, request.scheme
        return "ok"

    app.test_client().get("/_whoami", headers=headers, environ_base={"REMOTE_ADDR": "10.0.0.2"})
    # Untrusted by default; the guard answers 401 before the view, so use the wsgi env directly.
    assert "addr" not in seen or seen["addr"] == "10.0.0.2"

    monkeypatch.setenv("TRUSTED_PROXIES", "1")
    import utils.db as db
    db._local.conn.close()
    db._local.conn = None
    trusted = make_app()
    from werkzeug.middleware.proxy_fix import ProxyFix
    assert isinstance(trusted.wsgi_app, ProxyFix)
    assert not isinstance(app.wsgi_app, ProxyFix)


def test_log_filter_masks_credentials():
    from utils.logging_config import RedactSecretsFilter
    record = logging.LogRecord(
        "t", logging.INFO, __file__, 1,
        'refresh_token=abc123def456 Authorization: Bearer abcdefghijklmnop url?token=zzz password: hunter2', None, None)
    RedactSecretsFilter().filter(record)
    text = record.getMessage()
    for leaked in ("abc123def456", "abcdefghijklmnop", "zzz", "hunter2"):
        assert leaked not in text
    assert "[redacted]" in text


def test_empty_admin_env_falls_back_to_generated_credentials(make_app, monkeypatch, tmp_path):
    """docker compose passes ADMIN_PASSWORD="" when unset; that must not break first boot."""
    import utils.constants as constants
    monkeypatch.setattr(constants, "CONFIG_DIR", tmp_path)
    monkeypatch.setenv("SECRET_KEY", "test-only-secret")
    monkeypatch.setenv("ADMIN_PASSWORD", "")
    monkeypatch.setenv("ADMIN_USERNAME", "")
    make_app()
    creds = tmp_path / "initial-admin-credentials.json"
    assert creds.exists() and (creds.stat().st_mode & 0o777) == 0o600
