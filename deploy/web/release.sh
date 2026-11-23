#!/bin/sh
# The release step (deploy/compose.yml service `release`): runs once before the web server, the jobs and the ingest
# start, on every installation and every upgrade (docs/ops/upgrade.md), as the database's owner role, and stops at
# the first failure, so nothing serves a database it has not checked:
#   1. the deploy check (an unsafe or missing production setting: README, Starting a production server)
#   2. every CHECK constraint the unapplied migrations add, tried against the rows there are (a broken row is named
#      before anything is migrated, never found by a migration stopping half-way)
#   2b. the migrations
#   3. the app role's rights on what the migrations made (deploy/db/sql/grants.sql)
#   4. the static files of this image, with hashed names, copied to the volume the proxy serves; the files of the
#      release before stay there too, so a page still open in a browser loads its own
set -eu
cd /app
echo "release: check --deploy"
python manage.py check --deploy --fail-level WARNING
echo "release: the unapplied migrations' CHECK constraints against the rows there are"
python manage.py check_pending_constraints
echo "release: migrate"
python manage.py migrate --no-input
echo "release: the app role's rights"
python - <<'PY'
import os
from pathlib import Path

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()
from django.db import connection

with connection.cursor() as cursor:
    cursor.execute(Path('/app/deploy/db/sql/grants.sql').read_text(encoding='utf-8'))
PY
echo "release: static files"
cp -R /app/staticfiles/. /srv/static/
echo "release: done"
