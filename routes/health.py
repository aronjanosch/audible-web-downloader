"""Unauthenticated liveness/readiness probe for container orchestrators."""
from flask import Blueprint, jsonify

from utils.db import get_db

health_bp = Blueprint("health", __name__)


@health_bp.route("/healthz")
def healthz():
    """Report only whether the process and its database answer; no other detail."""
    try:
        get_db().execute("SELECT 1").fetchone()
    except Exception:
        return jsonify(status="error", db="error"), 503
    response = jsonify(status="ok", db="ok")
    response.headers["Cache-Control"] = "no-store"
    return response
