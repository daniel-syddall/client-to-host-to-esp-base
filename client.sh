#!/usr/bin/env bash
cd "$(dirname "$0")"
# Stop the compose project first.
docker compose down 2>/dev/null || true
# Stop any stale client container from this project (catches orphans docker compose down misses).
# Uses the directory name as the Compose project name, which is the Docker default.
PROJECT_NAME="$(basename "$(pwd)")"
docker ps -q --filter "name=${PROJECT_NAME}-client" | xargs -r docker stop 2>/dev/null || true
# Kill any host process holding port 1883 (e.g. system mosquitto).
fuser -k 1883/tcp 2>/dev/null || true
docker compose build --build-arg CACHEBUST="$(date +%s)" client
docker compose up --no-deps client "$@"
