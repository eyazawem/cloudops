#!/usr/bin/env bash
# Usage: source scripts/dev-env.sh
# Exports DATABASE_URL and TEST_DATABASE_URL for local development.
_root="$(git rev-parse --show-toplevel)"
set -a
source "${_root}/.env"
set +a
export DATABASE_URL="postgresql+psycopg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@127.0.0.1:5432/${POSTGRES_DB}"
export TEST_DATABASE_URL="postgresql+psycopg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@127.0.0.1:5432/${POSTGRES_DB}_test"
unset _root
