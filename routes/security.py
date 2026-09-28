"""Household password login and logout."""

from flask import Blueprint, current_app, jsonify, redirect, render_template, request, session, url_for

from utils.security import (
    _login_key, check_login_rate, login_user, verify_user,
)

security_bp = Blueprint("security", __name__)


@security_bp.get("/login")
def login_page():
    return render_template("security/login.html", next=request.args.get("next", ""), hide_sidebar=True)


@security_bp.post("/login")
def login():
    attempts = current_app.extensions["login_attempts"]
    key = _login_key()
    if not check_login_rate(attempts, key):
        return jsonify(error="Too many login attempts. Try again later."), 429
    data = request.get_json(silent=True) or request.form
    user = verify_user(data.get("username", ""), data.get("password", ""))
    if user is None:
        return jsonify(error="Invalid username or password"), 401
    attempts.pop(key, None)
    login_user(user)
    destination = data.get("next", "")
    if (not destination.startswith("/") or destination.startswith("//")
            or "\\" in destination or any(ord(char) < 32 for char in destination)):
        destination = "/"
    if request.is_json:
        return jsonify(success=True, redirect=destination, role=user["role"])
    return redirect(destination)


@security_bp.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("security.login_page"))
