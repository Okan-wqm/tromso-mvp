#!/bin/sh
# What scripts/test.sh runs inside the test runner's container (/app is the checkout; arguments go to `manage.py test`).
# Every command runs with deprecations as errors from its first import on (the models are imported before the test
# runner starts); once the tests start, config.test_runner.strict_warnings adds naive datetimes and the third-party list.
# With CHECKS=1 (CI does it) the project checks run first:
#   check                  every system check; a warning fails too
#   check --deploy         the deployment checks, with production-like settings (DEBUG off, a random key, a host): an
#                          issue not in DEPLOY_OPEN below fails
#   makemigrations --check no model change without its migration
#   data_map --check       docs/data-map.* match the code
#   update_catalogs        brings locale/*/django.po up to date; CI then fails when that changed a file (git diff)
set -eu
py() { python -W error::DeprecationWarning -W error::PendingDeprecationWarning "$@"; }

# The deployment issues still open, each until the production settings exist (README, CI and dependency updates).
# They are about the server's own settings, not the code; anything else check --deploy finds fails the run.
DEPLOY_OPEN="
mail.E001       the console mail backend: production sets an SMTP mailer (README, Email)
security.W004   SECURE_HSTS_SECONDS: to be set with HTTPS in production (irreversible for browsers, chosen then)
security.W008   SECURE_SSL_REDIRECT: HTTPS is ended at the reverse proxy in production
security.W012   SESSION_COOKIE_SECURE: set with HTTPS in production
security.W016   CSRF_COOKIE_SECURE: set with HTTPS in production
"

if [ "${CHECKS:-0}" = 1 ]; then (
  # The run's server holds no project database: the checks only ask the server for its version (and makemigrations
  # for the migrations applied: none), through its maintenance database.
  export DB_NAME=postgres
  py manage.py check --fail-level WARNING
  found=$(DJANGO_DEBUG=0 DJANGO_ALLOWED_HOSTS=farm.invalid \
    DJANGO_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(50))')" \
    py manage.py check --deploy --fail-level CRITICAL 2>&1) || { echo "$found"; exit 1; }
  echo "$found"
  open=$(echo "$DEPLOY_OPEN" | awk 'NF {print $1}')
  new=$(echo "$found" | grep -oE '^[^ ]+: \([a-z_]+\.[A-Z][0-9]+\)' | grep -oE '[a-z_]+\.[A-Z][0-9]+' | sort -u \
    | grep -vxF "$open" || true)
  if [ -n "$new" ]; then
    echo "check --deploy: issues not in DEPLOY_OPEN (scripts/testrunner/in-container.sh): $new"
    exit 1
  fi
  py manage.py makemigrations --check --dry-run
  py manage.py data_map --check
  py manage.py update_catalogs
) fi
py manage.py compile_catalogs >/dev/null
exec python -W error::DeprecationWarning -W error::PendingDeprecationWarning manage.py test --noinput "$@"
