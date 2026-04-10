#!/usr/bin/env bash
cd "$(dirname "$0")"
# Stop the compose project first.
docker compose down 2>/dev/null || true
# Stop every container whose name contains "-client" — catches orphans from
# any project name (e.g. if the project was started from a different directory).
docker ps -q --filter "name=client" | xargs -r docker stop 2>/dev/null || true
docker ps -aq --filter "name=client" | xargs -r docker rm 2>/dev/null || true
docker compose build --build-arg CACHEBUST="$(date +%s)" client
docker compose up --no-deps client "$@"
