# Names shared by up.sh and down.sh (sourced). Everything this CI owns in Docker starts with farm-ci.
export MSYS_NO_PATHCONV=1
RUNNER=farm-ci-runner                 # the container, and the runner's name on GitHub
IMAGE=farm-ci-runner:local
VOLUMES="farm-ci-work farm-ci-cache farm-ci-toolcache"
BUILDER_CONTAINER=buildx_buildkit_farm-ci0
BUILDER_STATE=buildx_buildkit_farm-ci0_state

need() { command -v "$1" >/dev/null 2>&1 || { echo "farm-ci: $1 is needed" >&2; exit 1; }; }

# The repository: CI_RUNNER_REPO (owner/name), else this checkout's origin.
repository() {
  if [ -n "${CI_RUNNER_REPO:-}" ]; then echo "$CI_RUNNER_REPO"; return; fi
  git -C "$(dirname "${BASH_SOURCE[0]}")" remote get-url origin \
    | sed -E 's#^(https://github\.com/|git@github\.com:)##; s#\.git$##'
}

# id, status and busy of the runner on GitHub, empty when it is not registered.
registered() {
  gh api "repos/$REPO/actions/runners" --paginate \
    --jq ".runners[] | select(.name == \"$RUNNER\") | \"\(.id) \(.status) \(.busy)\""
}

# What a job may have left in Docker (the names of job-clean.sh), removed by name.
remove_job_leftovers() {
  docker ps -aq --filter name=^farm-ci-job- | xargs -r docker rm -f -v >/dev/null
  docker rm -f "$BUILDER_CONTAINER" >/dev/null 2>&1 || true
  docker network ls --format '{{.Name}}' | { grep -E '^farm-ci-job-' || true; } | xargs -r docker network rm >/dev/null
  docker volume ls --format '{{.Name}}' | { grep -E '^farm-ci-job-' || true; } | xargs -r docker volume rm >/dev/null
}
