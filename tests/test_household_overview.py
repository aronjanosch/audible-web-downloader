"""Household overview: admin-only, token-health states and activity feed."""
import json
import os
import time

from test_security import household, _signed_in  # noqa: F401  (fixture reuse)


def test_overview_is_admin_only(household):
    _, client, admin, alice = household
    assert client.get("/api/household/overview").status_code == 401
    assert client.get("/household").status_code == 401
    _signed_in(client, alice)
    assert client.get("/api/household/overview").status_code == 403
    assert client.get("/household").status_code == 403
    _signed_in(client, admin)
    assert client.get("/household").status_code == 200
    body = client.get("/api/household/overview").json
    assert {m["name"] for m in body["members"]} == {"alice", "bob"}
    assert {a["name"] for a in body["attention"]} == {"alice", "bob"}  # neither is connected yet
    assert body["summary"]["members"] == 2


def test_token_health_states_and_events(household):
    from utils.config_manager import get_config_manager
    from utils.constants import get_auth_file_path
    from utils.token_health import account_health
    from utils.token_lifecycle import _set_authenticated
    app, client, admin, _ = household
    manager = get_config_manager()

    path = get_auth_file_path("alice")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"expires": time.time() + 1800}))
    _set_authenticated("alice", True)
    assert account_health("alice", manager.get_account("alice"))["state"] == "ok"

    path.write_text(json.dumps({"expires": time.time() - 5 * 3600}))
    assert account_health("alice", manager.get_account("alice"))["state"] == "warn"

    _set_authenticated("alice", False)  # revoked
    health = account_health("alice", manager.get_account("alice"))
    assert health["state"] == "err" and health["label"] == "Expired"
    assert account_health("bob", manager.get_account("bob"))["label"] == "Not connected"

    _signed_in(client, admin)
    activity = client.get("/api/household/overview").json["activity"]
    assert any("rejected" in e["text"] for e in activity)
    assert any("reconnected" in e["text"] for e in activity)


def test_events_table_migration_is_idempotent(household):
    from utils.db import get_db, migrate
    conn = get_db()
    conn.execute("DROP TABLE account_events")
    conn.execute("PRAGMA user_version = 4")
    conn.commit()
    migrate()
    migrate()
    assert conn.execute("PRAGMA user_version").fetchone()[0] >= 5
    conn.execute("SELECT COUNT(*) FROM account_events").fetchone()
