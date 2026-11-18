#!/usr/bin/env bash
# Stops the CI runner started by up.sh and removes it from GitHub (README, CI and dependency updates).
#
#   scripts/ci-runner/down.sh            stops and removes the container, what a job left in Docker, and the runner's
#                                        registration; refuses while a job is running
#   scripts/ci-runner/down.sh --force    also while a job is running (GitHub then fails that job)
#   scripts/ci-runner/down.sh --purge    after stopping, also removes the runner's volumes (work folder, caches, the
#                                        image builder's cache) and the images named farm-ci-*
# It removes by name only what this CI made (farm-ci-*, and the builder buildx_buildkit_farm-ci0): no prune, nothing
# of the development setup or of anybody's test run.
set -euo pipefail
cd "$(dirname "$0")"
. ./common.sh
need docker; need gh; need git
force=0 purge=0
for argument in "$@"; do
  case "$argument" in
    --force) force=1 ;;
    --purge) purge=1 ;;
    *) echo "usage: scripts/ci-runner/down.sh [--force] [--purge]" >&2; exit 2 ;;
  esac
done
REPO=$(repository)

state=$(registered)
if [ "${state##* }" = true ] && [ "$force" != 1 ]; then
  echo "farm-ci: a job is running on $RUNNER; wait for it, or stop anyway with --force (GitHub fails the job)" >&2
  exit 1
fi

docker stop -t 20 "$RUNNER" >/dev/null 2>&1 || true
docker rm -f -v "$RUNNER" >/dev/null 2>&1 || true
remove_job_leftovers
if [ -n "$state" ]; then
  gh api -X DELETE "repos/$REPO/actions/runners/${state%% *}" >/dev/null
fi
[ -z "$(registered)" ] || { echo "farm-ci: GitHub still lists $RUNNER for $REPO" >&2; exit 1; }
echo "farm-ci: $RUNNER is stopped and no longer registered for $REPO"

if [ "$purge" = 1 ]; then
  for volume in $VOLUMES "$BUILDER_STATE"; do docker volume rm "$volume" >/dev/null 2>&1 || true; done
  docker images --format '{{.Repository}}:{{.Tag}}' | { grep -E '^farm-ci-' || true; } | xargs -r docker rmi >/dev/null
  echo "farm-ci: the volumes $VOLUMES $BUILDER_STATE and the farm-ci-* images are removed"
fi
