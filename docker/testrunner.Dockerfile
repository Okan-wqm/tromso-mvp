# The Django test runner, with the water-chemistry core (chemcore) built from this checkout (README, chemcore).
#   docker build -f docker/testrunner.Dockerfile -t <tag> .
# Stages: chemcore-tools (Rust 1.88.0, maturin, cargo-deny: the gates of chemcore/scripts/test.sh),
# chemcore-wheel (the wheel, built --locked), runner (Python 3.12 with requirements and the wheel), tests (the runner
# and tblib, for scripts/test.sh). Every base
# image is pinned by digest, every Python package by hash, cargo-deny by sha256; crates by chemcore/Cargo.lock.
# The runner fails to build when the module does not import: there is no server without its chemistry.

FROM rust:1.88.0-slim-bookworm@sha256:38bc5a86d998772d4aec2348656ed21438d20fcdce2795b56ca434cf21430d89 AS chemcore-tools
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-venv git curl ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && rustup component add clippy rustfmt
COPY docker/chemcore-build.lock /tmp/chemcore-build.lock
RUN python3 -m venv /opt/maturin \
 && /opt/maturin/bin/pip install --no-cache-dir --require-hashes -r /tmp/chemcore-build.lock
ENV PATH=/opt/maturin/bin:$PATH
ARG CARGO_DENY_VERSION=0.20.2
ARG CARGO_DENY_SHA256=9f12ed4c49936e09b48bf862b595cde2fe64fcbd9d74dfacac6131ca824c8d5f
RUN curl -sSLf -o /tmp/cargo-deny.tgz \
      "https://github.com/EmbarkStudios/cargo-deny/releases/download/${CARGO_DENY_VERSION}/cargo-deny-${CARGO_DENY_VERSION}-x86_64-unknown-linux-musl.tar.gz" \
 && echo "${CARGO_DENY_SHA256}  /tmp/cargo-deny.tgz" | sha256sum -c - \
 && tar xzf /tmp/cargo-deny.tgz -C /tmp \
 && mv "/tmp/cargo-deny-${CARGO_DENY_VERSION}-x86_64-unknown-linux-musl/cargo-deny" /usr/local/cargo/bin/ \
 && rm -rf /tmp/cargo-deny*

FROM chemcore-tools AS chemcore-wheel
WORKDIR /src
COPY chemcore/ ./chemcore/
RUN cd chemcore/py && maturin build --release --locked --out /wheels

FROM python:3.12-slim@sha256:aa943ce411423c7582288f18707ff66eddcbaeb510502d747a72aeb34f30d159 AS runner
COPY docker/requirements.lock /tmp/requirements.lock
RUN pip install --no-cache-dir --require-hashes -r /tmp/requirements.lock
COPY --from=chemcore-wheel /wheels/ /wheels/
RUN pip install --no-cache-dir --no-index /wheels/chemcore-*.whl \
 && python -c "import chemcore; print('chemcore', chemcore.version(), chemcore.formula_version(), chemcore.core_hash())"
WORKDIR /app

# The test runs (scripts/test.sh): the runner and the test-only packages (tblib sends a worker's traceback to the main
# process of a parallel run).
FROM runner AS tests
COPY scripts/testrunner/requirements.txt /tmp/test-requirements.txt
RUN pip install --no-cache-dir -r /tmp/test-requirements.txt
