#!/bin/sh
set -eu

if [ "${1:-}" = "sleep" ]; then
    exec "$@"
fi

exec gitlab-migrator "$@"
