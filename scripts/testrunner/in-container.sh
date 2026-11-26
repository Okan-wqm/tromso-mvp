#!/bin/sh
# What scripts/test.sh runs inside the test runner's container (/app is the checkout; arguments go to `manage.py test`).
# Every command runs with deprecations as errors from its first import on (the models are imported before the test
# runner starts); once the tests start, config.test_runner.strict_warnings adds naive datetimes and the third-party list.
# With CHECKS=1 (CI does it) the project checks run first:
#   ruff check             the linter, errors only (ruff.toml: pyflakes F and E9): an undefined name, an unused import or
#                          variable, a key written twice; nothing is imported, so it says so before a server would
#   check                  every system check; a warning fails too
#   check --deploy         the deployment checks, with production-like settings (DEBUG off, a random key and digest key,
#                          a host, an SMTP server, a sender and an https public address): an issue not in DEPLOY_OPEN
#                          below fails (it is empty: the production settings are config/settings.py's)
#   makemigrations --check no model change without its migration
#   data_map --check       docs/data-map.* match the code
#   update_catalogs        brings locale/*/django.po up to date; CI then fails when that changed a file (git diff)
# The catalogs are compiled before the checks (core.W002) and again after update_catalogs, then the suite runs unless
# SUITE=0.
set -eu
py() { python -W error::DeprecationWarning -W error::PendingDeprecationWarning "$@"; }

# The deployment issues still open (README, CI and dependency updates): none since the production settings exist
# (config/settings.py, the production block). An issue goes here only with its reason and its end; anything else
# check --deploy finds fails the run.
DEPLOY_OPEN="
"

if [ "${CHECKS:-0}" = 1 ]; then (
  # The run's server holds no project database: the checks only ask the server for its version (and makemigrations
  # for the migrations applied: none), through its maintenance database.
  export DB_NAME=postgres
  # Reads the files only, and keeps no cache in the checkout (it is the developer's own folder, mounted).
  ruff check --no-cache .
  # The .mo files are built, never committed: a fresh checkout (CI) has none, and core.W002 would fail the check.
  py manage.py compile_catalogs >/dev/null
  py manage.py check --fail-level WARNING
  # The mail settings are the environment's (README, Email): with them Django's mail.E001 and the project's own
  # core.E002 to E005 are closed; without them the server does not start (core.tests_mail_settings).
  found=$(DJANGO_DEBUG=0 DJANGO_ALLOWED_HOSTS=farm.invalid \
    EMAIL_HOST=smtp.farm.invalid DEFAULT_FROM_EMAIL=console@farm.invalid PUBLIC_BASE_URL=https://farm.invalid \
    DJANGO_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(50))')"     DJANGO_AUDIT_DIGEST_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(40))')" \
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
# SUITE=0: the checks and the catalogs only, no tests (CI on a pull request)
[ "${SUITE:-1}" = 1 ] || exit 0
exec python -W error::DeprecationWarning -W error::PendingDeprecationWarning manage.py test --noinput "$@"
