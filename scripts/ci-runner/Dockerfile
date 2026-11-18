# The self-hosted runner of this repository's CI (README, CI and dependency updates; scripts/ci-runner/up.sh builds and
# starts it). GitHub's own runner (the release tarball, its checksum verified) on Ubuntu 24.04, the release the workflow
# ran on when it used GitHub's hosted machines, with what the jobs took from a hosted machine: git, the Docker client and
# buildx (the daemon is this machine's, through its socket), Chrome for the browser tests, rustup, a C toolchain, python3.
# Node and Python are installed by the jobs' own setup actions into /opt/hostedtoolcache (a volume).
#
# The jobs run as root inside this container: the containers a job starts write root's files into the checkout, which
# another user could not clean, and the Docker socket makes any user of it root on the daemon anyway. There is no sudo:
# nothing a job does may change the machine the runner lives on.
FROM ubuntu:24.04

# Move the two together (https://github.com/actions/runner/releases names the checksum). The runner also updates itself
# when GitHub asks for a newer one; a new container then starts from this version again and updates once more.
ARG RUNNER_VERSION=2.338.2
ARG RUNNER_SHA256=baebf204307bac6193480852732f0aba2ae97b6c5597c244f4d5558390147c40

ENV DEBIAN_FRONTEND=noninteractive LANG=C.UTF-8
SHELL ["/bin/bash", "-euo", "pipefail", "-c"]

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl git gnupg jq lsb-release openssl unzip xz-utils zstd \
      build-essential pkg-config python3 python3-venv \
      fonts-liberation fonts-dejavu-core fonts-noto-color-emoji \
 && install -d -m 0755 /etc/apt/keyrings \
 && curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc \
 && echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu noble stable" \
      > /etc/apt/sources.list.d/docker.list \
 && curl -fsSL https://dl.google.com/linux/linux_signing_key.pub | gpg --dearmor -o /etc/apt/keyrings/google.gpg \
 && echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/google.gpg] https://dl.google.com/linux/chrome/deb/ stable main" \
      > /etc/apt/sources.list.d/google-chrome.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends docker-ce-cli docker-buildx-plugin google-chrome-stable \
 && rm -f /etc/apt/sources.list.d/google-chrome.list \
 && rm -rf /var/lib/apt/lists/*

# rustup itself; the toolchains and cargo's files live on the cache volume (entrypoint.sh).
RUN curl -fsSL https://static.rust-lang.org/rustup/dist/x86_64-unknown-linux-gnu/rustup-init -o /usr/local/bin/rustup-init \
 && chmod 0755 /usr/local/bin/rustup-init

WORKDIR /opt/actions-runner
RUN curl -fsSL -o runner.tar.gz \
      "https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/actions-runner-linux-x64-${RUNNER_VERSION}.tar.gz" \
 && echo "${RUNNER_SHA256}  runner.tar.gz" | sha256sum -c - \
 && tar xzf runner.tar.gz && rm runner.tar.gz \
 && apt-get update && ./bin/installdependencies.sh && rm -rf /var/lib/apt/lists/*

COPY entrypoint.sh job-clean.sh /opt/farm-ci/
RUN chmod 0755 /opt/farm-ci/entrypoint.sh /opt/farm-ci/job-clean.sh

# Every cache a job fills is under FARM_CI_CACHE or the tool cache, both volumes (up.sh). The machine is shared: cargo
# compiles with at most CARGO_BUILD_JOBS processes, whatever the number of processors it sees.
ENV RUNNER_ALLOW_RUNASROOT=1 \
    CARGO_BUILD_JOBS=4 \
    FARM_CI_CACHE=/var/cache/farm-ci \
    AGENT_TOOLSDIRECTORY=/opt/hostedtoolcache \
    CARGO_HOME=/var/cache/farm-ci/cargo \
    RUSTUP_HOME=/var/cache/farm-ci/rustup \
    npm_config_cache=/var/cache/farm-ci/npm \
    PIP_CACHE_DIR=/var/cache/farm-ci/pip \
    PATH=/var/cache/farm-ci/cargo/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    ACTIONS_RUNNER_HOOK_JOB_STARTED=/opt/farm-ci/job-clean.sh \
    ACTIONS_RUNNER_HOOK_JOB_COMPLETED=/opt/farm-ci/job-clean.sh

ENTRYPOINT ["/opt/farm-ci/entrypoint.sh"]
