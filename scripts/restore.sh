#!/usr/bin/env bash
# Restore a backup made by scripts/backup.sh into an EMPTY (or moved-aside) config dir.
#
#   docker compose down
#   scripts/restore.sh backups/audible-config-YYYYmmdd-HHMMSS.tar.gz ./config
#   docker compose up -d
set -euo pipefail

ARCHIVE="${1:?usage: restore.sh ARCHIVE [CONFIG_DIR]}"
CONFIG_DIR="${2:-./config}"

[ -f "$ARCHIVE" ] || { echo "archive not found: $ARCHIVE" >&2; exit 1; }
if [ -e "$CONFIG_DIR/audible.db" ]; then
  echo "Refusing to overwrite existing $CONFIG_DIR/audible.db. Move $CONFIG_DIR aside first." >&2
  exit 1
fi
umask 077
mkdir -p "$CONFIG_DIR"
tar -C "$CONFIG_DIR" -xzf "$ARCHIVE"
# The container runs as uid/gid 1000.
if [ "$(id -u)" = 0 ]; then chown -R 1000:1000 "$CONFIG_DIR"; fi
echo "Restored into $CONFIG_DIR. If the container user differs from your uid, run: sudo chown -R 1000:1000 $CONFIG_DIR"
