"""The web container's health check (docker/testrunner.Dockerfile stage `web`): the sign-in page answers 200 through
gunicorn, asked as the proxy asks (a host the server answers to, X-Forwarded-Proto https), so a worker that cannot
render a page or reach the database shows as unhealthy."""
import http.client
import os
import sys

host = (os.environ.get('DJANGO_ALLOWED_HOSTS') or 'localhost').split(',')[0].strip().lstrip('.') or 'localhost'
try:
    connection = http.client.HTTPConnection('127.0.0.1', 8000, timeout=10)
    connection.request('GET', '/accounts/login/', headers={'Host': host, 'X-Forwarded-Proto': 'https'})
    status = connection.getresponse().status
except OSError as error:
    print(f'unhealthy: {error}')
    sys.exit(1)
print('ok' if status == 200 else f'unhealthy: the sign-in page answered {status}')
sys.exit(0 if status == 200 else 1)
