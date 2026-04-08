#!/usr/bin/env bash
cd "$(dirname "$0")"
docker compose build --build-arg CACHEBUST="$(date +%s)" host
docker compose up mosquitto host "$@"
