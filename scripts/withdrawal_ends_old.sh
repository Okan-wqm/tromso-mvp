#!/usr/bin/env bash
# scripts/withdrawal_ends_old.sh OUT [REF]: the "before" of a landing that changes the medicine withdrawal rule
# (README, Landing a change of the withdrawal rule): `manage.py withdrawal_ends dump` run with the OLD code (REF,
# default origin/main) against the development database, the dump written to OUT.
#
# It makes a throwaway worktree of REF next to the others (F:/dev/balik-wt/landing-old), copies this checkout's
# farm/management/commands/withdrawal_ends.py into it (its `dump` reads only what the old code has too), builds REF's
# test-runner image when it is missing, runs the dump in it on the compose project's network, and removes the worktree
# on every way out. The dump holds development-database data: OUT must lie outside every checkout (the repository is
# public), e.g. F:/dev/balik-notes/degree-days/ends-before-landing.json. Writes nothing to the database.
set -euo pipefail
OUT=${1:?usage: scripts/withdrawal_ends_old.sh OUT [REF]}
REF=${2:-origin/main}
HERE=$(cd "$(dirname "$0")/.." && { pwd -W 2>/dev/null || pwd; })
OLD=${LANDING_OLD:-F:/dev/balik-wt/landing-old}
export MSYS_NO_PATHCONV=1
case "$(cd "$(dirname "$OUT")" && { pwd -W 2>/dev/null || pwd; })" in
  "$HERE"*|F:/dev/balik-ciftligi*|F:/dev/balik-wt/*) echo "refused: OUT lies in a checkout; the dump holds dev-database data" >&2; exit 2;;
esac
[ -e "$OLD" ] && { echo "refused: $OLD exists (a landing in progress?); remove it first" >&2; exit 2; }
cleanup() { git -C "$HERE" worktree remove --force "$OLD" >/dev/null 2>&1 || true; }
trap cleanup EXIT INT TERM HUP
git -C "$HERE" worktree add --detach "$OLD" "$REF" >/dev/null
cp "$HERE/farm/management/commands/withdrawal_ends.py" "$OLD/farm/management/commands/withdrawal_ends.py"
IMG=$(cd "$OLD" && sh scripts/testrunner/image.sh build)
DIR=$(cd "$(dirname "$OUT")" && { pwd -W 2>/dev/null || pwd; })
docker run --rm --network balik-ciftligi_default -e DB_HOST=db -e DB_PORT=5432 -e COMPANY_NAME="Nordhav Akva" \
  -v "$OLD:/app" -v "$DIR:/out" -w /app "$IMG" \
  python manage.py withdrawal_ends dump --out "/out/$(basename "$OUT")"
echo "dump of $REF written to $OUT"
