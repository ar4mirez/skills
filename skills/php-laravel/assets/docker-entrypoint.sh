#!/bin/sh
# Container entrypoint: cache config/routes/views/events with the real runtime env,
# run migrations on the one host tagged `migrator`, then exec the role's command.
set -eu

php artisan optimize

if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
    # Not --isolated: with the database cache store its lock table doesn't exist
    # before the first migration. Kamal host tags keep this to one host instead.
    php artisan migrate --force
fi

exec "$@"
