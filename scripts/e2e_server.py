"""Throwaway app instance for browser checks. Fake data only, never real accounts.

Usage: uv run python scripts/e2e_server.py [port]
Audible OAuth is external, so the harness fakes its outcome: a harness-only route
``/__e2e/authenticate/<name>`` marks an account authenticated, and every library
fetch returns a fixed fake purchase list. Invite token is ``invited``.
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
root = Path(tempfile.mkdtemp(prefix="audible-e2e-"))
os.environ["AUDIBLE_CONFIG_DIR"] = str(root)
os.environ.update(SECRET_KEY="e2e-only-secret", ADMIN_PASSWORD="e2e-admin-password-123")

import routes.auth as auth_routes  # noqa: E402
import routes.invite as invite_routes  # noqa: E402
import utils.scheduler as scheduler  # noqa: E402
from utils.config_manager import get_config_manager  # noqa: E402

BOOKS = [
    {"asin": f"B0E2E{i:05d}", "title": title, "authors": author}
    for i, (title, author) in enumerate([
        ("The Long Way Home", "A. Writer"), ("Northern Lights", "B. Author"),
        ("A Quiet Harbour", "C. Novelist"), ("Clockwork Garden", "D. Storyteller"),
    ])
]
token_file = root / "auth.json"
token_file.write_text("{}")
scheduler.init_scheduler = lambda app: None
invite_routes.settings_manager.validate_invitation_token = lambda token: token == "invited"
auth_routes.get_auth_file_path = lambda name: token_file
auth_routes.get_cached_library = lambda name: BOOKS

from app import create_app  # noqa: E402

app = create_app()
app.config.update(SESSION_COOKIE_SECURE=False)


inner = app.wsgi_app


def wsgi(environ, start_response):
    path = environ["PATH_INFO"]
    if environ["REQUEST_METHOD"] == "POST" and path.startswith("/__e2e/authenticate/"):
        get_config_manager().update_account(path.rsplit("/", 1)[1], {"authenticated": True})
        start_response("200 OK", [("Content-Type", "application/json")])
        return [b'{"ok": true}']
    return inner(environ, start_response)


app.wsgi_app = wsgi
if __name__ == "__main__":
    app.run(port=int(sys.argv[1]) if len(sys.argv) > 1 else 5599)
