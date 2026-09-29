#!/usr/bin/env bash
# Back up everything that cannot be re-created: the SQLite database, settings and
# per-account Audible tokens (all under config/). Audiobooks in library/ are large
# and should be covered by your normal file backup.
#
#   scripts/backup.sh [CONFIG_DIR] [DEST_DIR]
#
# Produces DEST_DIR/audible-config-YYYYmmdd-HHMMSS.tar.gz (mode 0600).
# The archive contains Audible credentials: store it encrypted and off-host.
set -euo pipefail

CONFIG_DIR="${1:-./config}"
DEST_DIR="${2:-./backups}"
STAMP="$(date +%Y%m%d-%H%M%S)"

[ -d "$CONFIG_DIR" ] || { echo "config dir not found: $CONFIG_DIR" >&2; exit 1; }
mkdir -p "$DEST_DIR"
umask 077

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
cp -a "$CONFIG_DIR/." "$WORK/"

# Replace the live (possibly mid-write) database with a consistent online snapshot.
if [ -f "$CONFIG_DIR/audible.db" ]; then
  rm -f "$WORK/audible.db" "$WORK/audible.db-wal" "$WORK/audible.db-shm"
  python3 - "$CONFIG_DIR/audible.db" "$WORK/audible.db" <<'PY'
import sqlite3, sys
src = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
dst = sqlite3.connect(sys.argv[2])
with dst:
    src.backup(dst)
dst.close(); src.close()
PY
fi

OUT="$DEST_DIR/audible-config-$STAMP.tar.gz"
tar -C "$WORK" -czf "$OUT" .
chmod 600 "$OUT"
echo "Backup written: $OUT"
