"""Household identities and request authorization.

Audible credentials remain separate from household passwords.  A member can own
one Audible account; admins can administer all accounts and shared libraries.
"""

import os
import json
import secrets
import threading
import time
from datetime import timedelta

from flask import abort, g, jsonify, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from utils.db import get_db

SESSION_SECONDS = 12 * 60 * 60
LOGIN_WINDOW_SECONDS = 15 * 60
LOGIN_ATTEMPTS = 5
_attempt_lock = threading.Lock()


def create_user(username: str, password: str, role: str, account_name: str | None = None) -> dict:
    username = (username or "").strip()
    if not 3 <= len(username) <= 80 or not username.replace("_", "").replace("-", "").isalnum():
        raise ValueError("Username must be 3–80 letters, numbers, hyphens or underscores")
    if not password or not 12 <= len(password) <= 256:
        raise ValueError("Password must be 12–256 characters")
    if role not in ("admin", "member") or (role == "member" and not account_name):
        raise ValueError("A member must own an Audible account")
    conn = get_db()
    cursor = conn.execute(
        "INSERT INTO users (username,password_hash,role,account_name,created_at) VALUES (?,?,?,?,?)",
        (username, generate_password_hash(password), role, account_name, time.time()),
    )
    conn.commit()
    return dict(conn.execute("SELECT id,username,role,account_name FROM users WHERE id=?", (cursor.lastrowid,)).fetchone())


def current_user() -> dict | None:
    if hasattr(g, "household_user"):
        return g.household_user
    user_id = session.get("user_id")
    started = session.get("login_at", 0)
    if not user_id:
        g.household_user = None
        return None
    if not isinstance(started, (int, float)) or time.time() - started > SESSION_SECONDS:
        session.clear()
        g.household_user = None
        return None
    row = get_db().execute(
        "SELECT id,username,role,account_name FROM users WHERE id=?", (user_id,)
    ).fetchone()
    g.household_user = dict(row) if row else None
    if row is None:
        session.clear()
    return g.household_user


def login_user(user: dict) -> None:
    session.clear()
    session["user_id"] = user["id"]
    session["login_at"] = time.time()
    session.permanent = True
    if user["account_name"]:
        session["current_account"] = user["account_name"]
    if hasattr(g, "household_user"):
        del g.household_user


def require_member_account(account_name: str) -> dict:
    user = current_user()
    if user is None:
        abort(401)
    if user["role"] != "admin" and user["account_name"] != account_name:
        abort(403)
    return user


def bootstrap_admin() -> None:
    """Create an admin on first boot without stranding an upgraded household."""
    conn = get_db()
    if conn.execute("SELECT 1 FROM users WHERE role='admin' LIMIT 1").fetchone():
        return
    from utils.constants import CONFIG_DIR
    username = os.environ.get("ADMIN_USERNAME", "admin")
    if conn.execute("SELECT 1 FROM users WHERE username=? COLLATE NOCASE", (username,)).fetchone():
        username = "household-owner"
    password = os.environ.get("ADMIN_PASSWORD")
    if password is None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        path = CONFIG_DIR / "initial-admin-credentials.json"
        if path.exists():
            credentials = json.loads(path.read_text(encoding="utf-8"))
            username, password = credentials["username"], credentials["password"]
        else:
            password = secrets.token_urlsafe(36)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump({"username": username, "password": password}, stream)
                stream.flush()
                os.fsync(stream.fileno())
    create_user(username, password, "admin")


def _login_key() -> str:
    # Neither X-Forwarded-For nor submitted username is trusted for bypass control.
    return request.remote_addr or "unknown"


def install_security(app, csrf):
    app.config.update(
        PERMANENT_SESSION_LIFETIME=timedelta(seconds=SESSION_SECONDS),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE", "1") != "0",
        WTF_CSRF_CHECK_DEFAULT=False,
    )
    # A single worker is pinned by gunicorn.conf.py. Login attempts are process-local;
    # this is a bounded defensive layer, not a distributed abuse prevention system.
    attempts: dict[str, list[float]] = {}

    @app.before_request
    def guard_request():
        endpoint = request.endpoint or ""
        if endpoint == "static":
            return None
        if endpoint in {"security.login", "security.login_page"}:
            if request.method == "POST":
                csrf.protect()
            return None
        if endpoint.startswith("invite."):
            # Invite routes must validate their invitation token. The registration
            # POST is CSRF-protected; OAuth callbacks use one-time flow IDs.
            if request.method not in {"GET", "HEAD", "OPTIONS"} and endpoint not in {
                "invite.login_callback", "invite.account_login_callback"
            }:
                csrf.protect()
            return None
        user = current_user()
        if user is None:
            if request.path.startswith("/api/") or request.method not in {"GET", "HEAD", "OPTIONS"}:
                return jsonify(error="Authentication required"), 401
            return render_template("security/login.html", next=request.path, hide_sidebar=True), 401
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            csrf.protect()
        # Admin-only operations include all shared data mutation. Explicit member
        # routes are checked for ownership below.
        member_endpoints = {
            "main.get_session_state", "main.get_accounts", "main.select_account",
            "auth.start_login", "auth.login_page", "auth.login_callback", "auth.login_status",
            "auth.check_auth", "auth.authenticate", "auth.fetch_library_route", "auth.fetch_all_libraries",
            "scheduler.get_auto_download_status", "scheduler.configure_auto_download", "scheduler.trigger_auto_download",
        }
        if user["role"] != "admin":
            if endpoint not in member_endpoints and endpoint not in {"main.index", "security.logout"}:
                return jsonify(error="Administrator required"), 403
            account = (request.view_args or {}).get("account_name")
            if account is None and endpoint in {"auth.check_auth", "auth.authenticate", "auth.fetch_library_route"}:
                account = (request.get_json(silent=True) or {}).get("account_name")
            if account is not None and account != user["account_name"]:
                return jsonify(error="Account access denied"), 403
            if endpoint == "auth.fetch_all_libraries" and request.args.get("force"):
                # A member's fetch-all is scoped in the route implementation.
                pass
        return None

    @app.after_request
    def secure_response(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = "frame-ancestors 'none'; object-src 'none'; base-uri 'self'"
        if request.path.startswith(("/api/", "/auth/", "/invite/")):
            response.headers["Cache-Control"] = "no-store"
        return response

    return attempts


def check_login_rate(attempts: dict, key: str) -> bool:
    now = time.monotonic()
    with _attempt_lock:
        recent = [t for t in attempts.get(key, []) if now - t < LOGIN_WINDOW_SECONDS]
        if len(recent) >= LOGIN_ATTEMPTS:
            attempts[key] = recent
            return False
        # Reserve a slot before the password hash check, so concurrent requests
        # cannot all pass the limit at once.
        attempts[key] = recent + [now]
        return True


def verify_user(username: str, password: str) -> dict | None:
    row = get_db().execute("SELECT * FROM users WHERE username=? COLLATE NOCASE", (username,)).fetchone()
    if row is None or not check_password_hash(row["password_hash"], password):
        return None
    return {key: row[key] for key in ("id", "username", "role", "account_name")}
