#!/bin/bash
# What a job leaves behind on the runner's machine, removed (README, CI and dependency updates). A hosted machine was
# new for every job; this one is not, and it is shared with the development setup.
#
#   job-clean.sh           the runner runs it before and after every job (ACTIONS_RUNNER_HOOK_JOB_STARTED and
#                          _COMPLETED, set in the image, so no workflow can leave it out): the checkout folder is
#                          emptied (a job's containers write into it, and the next job must not read what they left),
#                          then the Docker part below
#   job-clean.sh docker    the Docker part alone, the last step of every job that starts a container (`if: always()`,
#                          so after a failure or a cancellation too): the containers, networks and volumes whose name
#                          starts with farm-ci-job- (the only names the workflow gives)
# The image builder's container (buildx_buildkit_farm-ci0) is removed by the hook only, after the job's own steps: its
# cache is a volume and stays. By name only: nothing else on this machine's Docker is looked at, and nothing is pruned.
set -uo pipefail

if [ "${1:-}" != docker ]; then
  if [ -n "${GITHUB_WORKSPACE:-}" ] && [ -d "$GITHUB_WORKSPACE" ]; then
    find "$GITHUB_WORKSPACE" -mindepth 1 -delete || { echo "farm-ci: the checkout folder could not be emptied" >&2; exit 1; }
  fi
  docker rm -f -v buildx_buildkit_farm-ci0 >/dev/null 2>&1 || true
fi

names() { grep -E '^farm-ci-job-' || true; }
docker ps -aq --filter name=^farm-ci-job- | xargs -r docker rm -f -v >/dev/null
docker network ls --format '{{.Name}}' | names | xargs -r docker network rm >/dev/null
docker volume ls --format '{{.Name}}' | names | xargs -r docker volume rm >/dev/null
left=$(docker ps -a --format '{{.Names}}' | names)
[ -z "$left" ] || { echo "farm-ci: still there: $left" >&2; exit 1; }
exit 0
