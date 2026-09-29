"""Exercise the ABS integration against a REAL Audiobookshelf server (fake data only).

Usage: uv run python scripts/abs_live_check.py http://localhost:13399 /path/to/fake/books
Start ABS however you like (Docker image or `node index.js`) with an empty config dir and a
folder of fake books. The script initialises ABS with a throwaway root user, creates a library
over the folder, then checks scan trigger, catalog listing, ASIN reconciliation and the
behaviour when ABS goes away (bad URL) or rejects the token.
"""
import sys
import tempfile
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
base, books_dir = sys.argv[1].rstrip("/"), sys.argv[2]

status = requests.get(f"{base}/status", timeout=8).json()
print("ABS version:", status["serverVersion"])
if not status.get("isInit"):
    requests.post(f"{base}/init", json={"newRoot": {"username": "root", "password": "throwaway-pass-123"}}, timeout=8).raise_for_status()
login = requests.post(f"{base}/login", json={"username": "root", "password": "throwaway-pass-123"}, timeout=8)
login.raise_for_status()
token = login.json()["user"]["token"]
auth = {"Authorization": f"Bearer {token}"}
library = requests.post(f"{base}/api/libraries", headers=auth, timeout=8, json={
    "name": "fake", "folders": [{"fullPath": books_dir}], "mediaType": "book",
}).json()
library_id = library["id"]

import utils.db as db  # noqa: E402
from app.services import audiobookshelf as service  # noqa: E402

db.init_db(Path(tempfile.mkdtemp()) / "live.db")
db.migrate()
conn = db.get_db()
for asin, title, authors, state in [
    ("B0FAKE0001", "Fake Book One", "Fake Author", "downloaded"),
    ("B0NOTINABS", "Not In Abs", "Nobody", "downloaded"),
]:
    conn.execute("INSERT INTO books (asin, title, authors, status, added_at, updated_at) VALUES (?,?,?,?,?,?)", (asin, title, authors, state, time.time(), time.time()))
conn.commit()

client = service.AudiobookshelfClient(base, token, library_id)
client.trigger_scan()
print("scan accepted")
items = []
for _ in range(30):
    items = client.list_items()
    if items:
        break
    time.sleep(2)
print("indexed items:", [(i["media"]["metadata"].get("title"), i["media"]["metadata"].get("asin")) for i in items])
counts = service.reconcile_items(items)
print("reconcile:", counts)
rows = {r["asin"]: (r["status"], r["match_method"]) for r in conn.execute("SELECT asin,status,match_method FROM abs_items")}
print("abs_items:", rows)
assert rows["B0FAKE0001"] == ("matched", "asin"), rows
assert rows["B0NOTINABS"][0] == "pending", rows

before = dict(rows)
for label, bad in [("wrong token", service.AudiobookshelfClient(base, "bad-token", library_id)),
                   ("ABS offline", service.AudiobookshelfClient("http://127.0.0.1:1", token, library_id))]:
    try:
        bad.list_items()
    except service.AudiobookshelfError as exc:
        print(f"{label}: AudiobookshelfError({exc}) - state untouched")
    else:
        raise SystemExit(f"{label}: expected AudiobookshelfError")
after = {r["asin"]: (r["status"], r["match_method"]) for r in conn.execute("SELECT asin,status,match_method FROM abs_items")}
assert after == before
print("LIVE ABS CHECK PASSED")
