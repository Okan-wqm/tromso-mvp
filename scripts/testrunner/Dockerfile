# The image the tests run in. Built from the checkout (scripts/testrunner/image.sh says how, and its tag: a hash of
# everything it is built from, so checkouts with different requirements never share one); Dockerfile.dockerignore
# beside this file lets only the two requirements files into the build.
FROM python:3.12-slim AS tests
WORKDIR /deps
COPY requirements.txt ./requirements.txt
COPY scripts/testrunner/requirements.txt ./test-requirements.txt
RUN pip install --no-cache-dir -r requirements.txt -r test-requirements.txt
WORKDIR /app
