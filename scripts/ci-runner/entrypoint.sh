#!/bin/bash
# What the runner's container runs (scripts/ci-runner/Dockerfile): registers the runner with the repository, then listens
# for jobs, one at a time. up.sh gives the registration token through a file in memory (/run/farm-ci/token, written with
# `docker exec -i`): it is in no environment variable, no `docker inspect` and no image, and it is deleted once read.
# RUNNER_URL, RUNNER_NAME and RUNNER_WORK come from up.sh.
set -euo pipefail
cd /opt/actions-runner

mkdir -p "$FARM_CI_CACHE" "$AGENT_TOOLSDIRECTORY" "$RUNNER_WORK"
# The checkout belongs to whoever made the volume; git refuses another user's repository otherwise.
git config --global --add safe.directory '*'
if [ ! -x "$CARGO_HOME/bin/rustup" ]; then
  rustup-init -y --no-modify-path --default-toolchain none --profile minimal >/dev/null
fi

if [ ! -f .runner ]; then
  for _ in $(seq 1 240); do
    [ -s /run/farm-ci/token ] && break
    sleep 0.5
  done
  [ -s /run/farm-ci/token ] || { echo "farm-ci: no registration token arrived (scripts/ci-runner/up.sh gives it)" >&2; exit 1; }
  token=$(cat /run/farm-ci/token)
  rm -f /run/farm-ci/token
  ./config.sh --unattended --url "$RUNNER_URL" --token "$token" --name "$RUNNER_NAME" --labels farm \
    --work "$RUNNER_WORK" --replace
  unset token
fi
exec ./run.sh
