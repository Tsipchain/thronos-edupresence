#!/bin/sh
set -e

# Ensure the data directory exists and is writable.
# This runs as root so it works even after Railway mounts the volume.
mkdir -p /data
chmod 777 /data

echo "[entrypoint] Data directory ready: /data"
echo "[entrypoint] Starting uvicorn on port ${PORT:-8000}..."

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
