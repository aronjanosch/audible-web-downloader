#!/bin/bash
set -e

# Default to UID/GID 1000 if not specified
PUID=${PUID:-1000}
PGID=${PGID:-1000}

echo "Starting with UID: $PUID, GID: $PGID"

# Create group if it doesn't exist
if ! getent group appuser > /dev/null 2>&1; then
    groupadd -g "$PGID" appuser
fi

# Create user if it doesn't exist
if ! id appuser > /dev/null 2>&1; then
    useradd -u "$PUID" -g "$PGID" -m -s /bin/bash appuser
fi

# Update ownership of application directories
chown -R appuser:appuser /app/config /app/downloads /app/library 2>/dev/null || true

# Execute the command as appuser
exec gosu appuser "$@"

