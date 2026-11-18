#!/usr/bin/env bash
# Starts the CI runner of this repository on this machine's Docker (README, CI and dependency updates).
#
#   scripts/ci-runner/up.sh      builds the runner's image when it changed, starts the container farm-ci-runner,
#                                registers it with the repository and waits until GitHub shows it online
#   scripts/ci-runner/down.sh    stops it and removes it from GitHub (the caches stay; --purge removes them too)
#
# Needs docker and gh, signed in as the repository's owner (the registration token is asked with gh, lives an hour, and
# goes into the container through a pipe: no file, no variable, no output holds it).
# It REFUSES a repository that is not private: a self-hosted runner runs whatever a workflow says, on this machine, and
# on a public repository anybody's pull request is such a workflow.
# One container, so one job at a time. The container holds memory while it waits (README says how much); down.sh frees
# it, and the jobs pushed meanwhile wait on GitHub (a day at most) until the next up.sh.
set -euo pipefail
cd "$(dirname "$0")"
. ./common.sh
need docker; need gh; need git
REPO=$(repository)

private=$(gh api "repos/$REPO" --jq .private)
[ "$private" = true ] || { echo "farm-ci: $REPO is not a private repository: no runner is started for it" >&2; exit 1; }

state=$(registered)
if [ "$(docker inspect -f '{{.State.Running}}' "$RUNNER" 2>/dev/null)" = true ] && [ "${state#* }" != "${state#* online }" ]; then
  echo "farm-ci: $RUNNER is already running and online for $REPO"
  exit 0
fi

docker build -q -t "$IMAGE" . >/dev/null
docker rm -f "$RUNNER" >/dev/null 2>&1 || true
remove_job_leftovers
for volume in $VOLUMES; do docker volume create "$volume" >/dev/null; done
# The work folder is a volume mounted at the path the daemon itself knows it by, so a path inside it means the same
# files to a job step and to the daemon (`docker run -v "$PWD:/repo"`, the binds of scripts/test.sh). A folder of the
# Docker VM would not do: in Docker Desktop such a folder lives in memory and is gone at a restart.
WORK=$(docker volume inspect -f '{{.Mountpoint}}' farm-ci-work)

docker run -d --name "$RUNNER" --network host --tmpfs /run/farm-ci:mode=0700 \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "farm-ci-work:$WORK" -v farm-ci-cache:/var/cache/farm-ci -v farm-ci-toolcache:/opt/hostedtoolcache \
  -e RUNNER_URL="https://github.com/$REPO" -e RUNNER_NAME="$RUNNER" -e RUNNER_WORK="$WORK" \
  "$IMAGE" >/dev/null
gh api -X POST "repos/$REPO/actions/runners/registration-token" --jq .token \
  | docker exec -i "$RUNNER" sh -c 'umask 077; cat > /run/farm-ci/token.part && mv /run/farm-ci/token.part /run/farm-ci/token'

for _ in $(seq 1 60); do
  state=$(registered)
  if [ "${state#* }" != "${state#* online }" ]; then
    echo "farm-ci: $RUNNER is online for $REPO (labels self-hosted, linux, x64, farm); stop it with scripts/ci-runner/down.sh"
    exit 0
  fi
  [ "$(docker inspect -f '{{.State.Running}}' "$RUNNER" 2>/dev/null)" = true ] || break
  sleep 2
done
echo "farm-ci: the runner did not come online; its log:" >&2
docker logs --tail 40 "$RUNNER" >&2 || true
exit 1
