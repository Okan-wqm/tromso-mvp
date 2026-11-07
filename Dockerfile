# The platform's Python image: the background worker (docker-compose.yml service `worker`, `manage.py run_worker`)
# and, on a server, the web process run from the same code. The same recipe as the test runner image.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN python manage.py compile_catalogs
CMD ["python", "manage.py", "run_worker"]
