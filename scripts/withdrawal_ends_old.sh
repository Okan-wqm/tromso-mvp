#!/usr/bin/env bash
# scripts/withdrawal_ends_old.sh OUT [REF]: the "before" of a landing that changes the medicine withdrawal rule
# (README, Landing a change of the withdrawal rule): `manage.py withdrawal_ends dump` run with the OLD code (REF,
# default the local `main`, what the dev server runs) against the development database, the dump written to OUT.
#
# It makes a throwaway worktree of REF next to the others (F:/dev/balik-wt/landing-old), copies this checkout's
# farm/management/commands/withdrawal_ends.py into it (its `dump` reads only what the old code has too), builds REF's
# test-runner image when it is missing, runs the dump in it on the compose project's network, and removes the worktree
# on every way out. The dump holds development-database data: OUT must lie outside every git checkout (the repository
# is public), e.g. F:/dev/balik-notes/degree-days/ends-before-landing.json, written with forward slashes and no space.
# Writes nothing to the database.
#
# A rehearsal against a throwaway database instead of the development one: WITHDRAWAL_ENDS_NETWORK (the docker network)
# and WITHDRAWAL_ENDS_DB (the -e DB_... options); WITHDRAWAL_ENDS_MIGRATE=1 then migrates that database with the old
# code first. A migration is refused on the compose project's network whatever the options say, and on any network
# against the compose database's host (db, balik-ciftligi-db...) or the port it is published on (5433). OUT must lie
# where git says "not a git repository": any other git answer or error is refused.
#
# Every refusal comes before anything is made; each exits 2 and says "refused".
set -euo pipefail
OUT=${1:?usage: scripts/withdrawal_ends_old.sh OUT [REF]}
REF=${2:-main}
COMPOSE=balik-ciftligi_default
NETWORK=${WITHDRAWAL_ENDS_NETWORK:-$COMPOSE}
DB=${WITHDRAWAL_ENDS_DB:--e DB_HOST=db -e DB_PORT=5432}
refuse() { echo "refused: $*" >&2; exit 2; }
case "$OUT" in
  *\\*) refuse "OUT has a backslash ($OUT): write the path with forward slashes, F:/dev/balik-notes/...";;
  *" "*) refuse "OUT has a space ($OUT): choose a path without one";;
  */*) ;;
  *) refuse "OUT names no folder ($OUT): give its full path";;
esac
if [ "${WITHDRAWAL_ENDS_MIGRATE:-}" = 1 ]; then
  if [ "$NETWORK" = "$COMPOSE" ]; then
    refuse "WITHDRAWAL_ENDS_MIGRATE on the compose network ($COMPOSE): that is the development database"
  fi
  set -f                                    # the options' words, never file names
  for word in $DB; do
    case "$word" in
      DB_HOST=db|DB_HOST=balik-ciftligi-db*|DB_PORT=5433)
        refuse "WITHDRAWAL_ENDS_MIGRATE with $word: that is the development database (the compose db, or its port)";;
    esac
  done
  set +f
fi
[ -d "$(dirname "$OUT")" ] || refuse "the folder of OUT does not exist: $(dirname "$OUT")"
DIR=$(cd "$(dirname "$OUT")" && { pwd -W 2>/dev/null || pwd; })
# Only git's own "not a git repository" lets OUT through: any other answer or error (a dubious-ownership refusal, no
# git at all) could hide a checkout.
if CHECKOUT=$(git -C "$DIR" rev-parse --is-inside-work-tree 2>&1); then
  refuse "OUT lies in a git checkout ($DIR): the dump holds development-database data"
fi
case "$CHECKOUT" in
  *"not a git repository"*) ;;
  *) refuse "git cannot say that OUT lies in no checkout ($DIR): $CHECKOUT";;
esac
HERE=$(cd "$(dirname "$0")/.." && { pwd -W 2>/dev/null || pwd; })
OLD=${LANDING_OLD:-F:/dev/balik-wt/landing-old}
[ -e "$OLD" ] && refuse "$OLD exists (a landing in progress?); remove it first"
if [ "$REF" = main ] && [ "$(git -C "$HERE" rev-parse main)" != "$(git -C "$HERE" rev-parse origin/main)" ]; then
  refuse "the local main is not origin/main: fetch, and make main what the dev server runs, first"
fi
export MSYS_NO_PATHCONV=1
cleanup() { git -C "$HERE" worktree remove --force "$OLD" >/dev/null 2>&1 || true; }
trap cleanup EXIT INT TERM HUP
git -C "$HERE" worktree add --detach "$OLD" "$REF" >/dev/null
cp "$HERE/farm/management/commands/withdrawal_ends.py" "$OLD/farm/management/commands/withdrawal_ends.py"
IMG=$(cd "$OLD" && sh scripts/testrunner/image.sh build)
FIRST=
if [ "${WITHDRAWAL_ENDS_MIGRATE:-}" = 1 ]; then
  FIRST='python manage.py migrate --noinput >/dev/null && '
fi
# shellcheck disable=SC2086 # the -e options are words, split on purpose
docker run --rm --network "$NETWORK" $DB -e COMPANY_NAME="Nordhav Akva" \
  -v "$OLD:/app" -v "$DIR:/out" -w /app "$IMG" \
  sh -c "${FIRST}python manage.py withdrawal_ends dump --out '/out/$(basename "$OUT")'"
echo "dump of $REF written to $OUT"
