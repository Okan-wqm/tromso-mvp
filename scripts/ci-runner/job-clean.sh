#!/bin/bash
# The runner runs this before and after every job (ACTIONS_RUNNER_HOOK_JOB_STARTED and _COMPLETED, set in the image, so
# no workflow can leave it out). A hosted machine was new for every job; this one is not, so each job starts from, and
# leaves, an empty checkout and none of a job's own containers:
#   - the checkout folder is emptied (a job's containers write into it, the next job must not read what they left);
#   - what a job made in Docker and a killed job could not remove: containers, networks and volumes whose name starts
#     with farm-ci-job- (the only names the workflow gives), and the image builder's container (its cache is a volume
#     and stays).
# By name only: nothing else on this machine's Docker is looked at, and nothing is pruned.
set -uo pipefail

if [ -n "${GITHUB_WORKSPACE:-}" ] && [ -d "$GITHUB_WORKSPACE" ]; then
  find "$GITHUB_WORKSPACE" -mindepth 1 -delete || { echo "farm-ci: the checkout folder could not be emptied" >&2; exit 1; }
fi

names() { grep -E '^farm-ci-job-' || true; }
docker ps -aq --filter name=^farm-ci-job- | xargs -r docker rm -f -v >/dev/null
docker rm -f buildx_buildkit_farm-ci0 >/dev/null 2>&1 || true
docker network ls --format '{{.Name}}' | names | xargs -r docker network rm >/dev/null
docker volume ls --format '{{.Name}}' | names | xargs -r docker volume rm >/dev/null
exit 0
