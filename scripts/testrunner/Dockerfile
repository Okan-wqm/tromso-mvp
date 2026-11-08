# The image the tests run in (scripts/test.sh builds it, tagged by the hash of the requirements, so checkouts with
# different requirements never share one). Built from a context holding only the two requirements files.
FROM python:3.12-slim
WORKDIR /deps
COPY requirements.txt test-requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r test-requirements.txt
WORKDIR /app
