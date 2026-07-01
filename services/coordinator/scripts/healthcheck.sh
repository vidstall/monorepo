#!/usr/bin/env bash
set -euo pipefail

REDIS_HOST="${REDIS_HOST:-127.0.0.1}"
REDIS_PORT="${REDIS_PORT:-6379}"

if ! command -v redis-cli >/dev/null 2>&1; then
  if command -v docker >/dev/null 2>&1 && [ "${REDIS_HOST}" = "127.0.0.1" ] && [ "${REDIS_PORT}" = "6379" ]; then
    response="$(docker exec xaisen-coordinator-redis redis-cli ping)"
  else
    echo "redis-cli is required for coordinator health checks" >&2
    exit 127
  fi
else
  response="$(redis-cli -h "${REDIS_HOST}" -p "${REDIS_PORT}" ping)"
fi

if [ "${response}" != "PONG" ]; then
  echo "unexpected Redis response: ${response}" >&2
  exit 1
fi

echo "coordinator Redis is healthy at ${REDIS_HOST}:${REDIS_PORT}"
