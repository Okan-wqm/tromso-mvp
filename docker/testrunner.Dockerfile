# The Django test runner and the production web server, with the water-chemistry core (chemcore) built from this
# checkout (README, chemcore; docs/ops/).
#   docker build -f docker/testrunner.Dockerfile -t <tag> .                 the test runner (target tests, the last stage)
#   docker build -f docker/testrunner.Dockerfile --target web -t <tag> .    the production web image (deploy/compose.yml)
# Stages, in this order (the last, tests, is what a build without --target makes): chemcore-tools (Rust 1.88.0, maturin,
# cargo-deny: the gates of chemcore/scripts/test.sh), chemcore-wheel (the wheel, built --locked), runner (Python 3.12
# with requirements and the wheel), browser (the TypeScript compiled), web (the runner, the application and gunicorn),
# tests (the runner and tblib, for scripts/test.sh).
# Every base image is pinned by digest, every Python package by hash, cargo-deny by sha256; crates by chemcore/Cargo.lock.
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

# The browser code of the production image: frontend/*.ts compiled into static/js (README, Browser code). The committed
# stylesheets (static/css/tw.css, tokens.css) are used as they are: CI checks they are what their sources build.
FROM node:22-bookworm-slim@sha256:e9f565d32859f0cbfb52125eafe8be39390f24dac302dc3cdf566e8ba3ab21ee AS browser
WORKDIR /src
COPY package.json package-lock.json tsconfig.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund
COPY frontend/ ./frontend/
RUN npx tsc -p tsconfig.json

# The production web server (deploy/compose.yml, docs/ops/): the runner (Python, the hashed requirements with gunicorn,
# the chemistry core), the application, its compiled browser code, the catalogs and the static files under hashed names
# (collectstatic into /app/staticfiles), run as an unprivileged user. The release step migrates and copies the static
# files to the proxy's volume (deploy/web/release.sh); `core/tests_deploy.py` holds the list below to INSTALLED_APPS.
FROM runner AS web
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DJANGO_DEBUG=0 DJANGO_MEDIA_ROOT=/srv/media
RUN useradd --system --uid 10002 --user-group --no-create-home --home-dir /app --shell /usr/sbin/nologin balik \
 && mkdir -p /srv/static /srv/media /broker-auth \
 && chown balik:balik /srv/static /srv/media /broker-auth
WORKDIR /app
COPY manage.py ./manage.py
COPY config/ ./config/
COPY core/ ./core/
COPY farm/ ./farm/
COPY knowledge/ ./knowledge/
COPY messaging/ ./messaging/
COPY inventory/ ./inventory/
COPY reports/ ./reports/
COPY tasks/ ./tasks/
COPY hr/ ./hr/
COPY experiments/ ./experiments/
COPY monitoring/ ./monitoring/
COPY sensors/ ./sensors/
COPY alarms/ ./alarms/
COPY templates/ ./templates/
COPY static/ ./static/
COPY locale/ ./locale/
COPY chemcore/EXPECTED ./chemcore/EXPECTED
COPY deploy/web/ ./deploy/web/
COPY deploy/db/sql/grants.sql ./deploy/db/sql/grants.sql
COPY --from=browser /src/static/js/ ./static/js/
# Built here, never at run time (the root file system is read-only): the .mo catalogs, then the static files under
# hashed names with their manifest (DEBUG off is what selects ManifestStaticFilesStorage; no database is asked).
RUN DJANGO_DEBUG=1 python manage.py compile_catalogs \
 && python manage.py collectstatic --no-input --skip-checks \
 && python -c "import json; m = json.load(open('/app/staticfiles/staticfiles.json')); print('static files:', len(m['paths']))"
USER balik
EXPOSE 8000
STOPSIGNAL SIGTERM
HEALTHCHECK --interval=30s --timeout=15s --start-period=60s --retries=3 CMD ["python", "/app/deploy/web/healthcheck.py"]
CMD ["gunicorn", "-c", "/app/deploy/web/gunicorn.conf.py", "config.wsgi:application"]

# The test runs (scripts/test.sh): the runner and the test-only packages (tblib sends a worker's traceback to the main
# process of a parallel run).
FROM runner AS tests
COPY scripts/testrunner/requirements.txt /tmp/test-requirements.txt
RUN pip install --no-cache-dir -r /tmp/test-requirements.txt
