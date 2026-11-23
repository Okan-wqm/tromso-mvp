"""The production WSGI server's settings (gunicorn; deploy/compose.yml service `web`, docs/ops/install.md).

  gunicorn -c /app/deploy/web/gunicorn.conf.py config.wsgi:application

- Before the first worker starts, the master runs `manage.py check --deploy --fail-level WARNING` (on_starting): a
  production setting that is unsafe or missing (a development key, `*` among the hosts, an http public address, no
  SMTP server, no digest key, HSTS off, ...) stops the server here, with the check's own words, instead of serving.
- Threaded workers (gthread): the account e-mails leave on a worker thread of each process (core.accountmail), which
  a server without threads would never run (README, Starting a production server).
- SIGTERM ends a worker in order (what it is serving, then its exit handlers: the mail under way is sent), within
  graceful_timeout; compose gives the container longer than that (stop_grace_period).
- Every number can be set from the environment; the defaults suit a farm's server of 2 to 4 cores.
"""
import os


def _number(name, default):
    value = os.environ.get(name, '')
    try:
        number = int(value) if value else default
    except ValueError:
        raise SystemExit(f'{name}={value!r} is not a whole number.') from None
    if number < 1:
        raise SystemExit(f'{name} must be 1 or more.')
    return number


bind = os.environ.get('GUNICORN_BIND', '0.0.0.0:8000')
worker_class = 'gthread'
# Processes and threads: 3 x 4 serve twelve requests at a time; each thread keeps its own database connection
# (DB_CONN_MAX_AGE), so workers x threads x the web containers must stay well below the database's max_connections.
workers = _number('GUNICORN_WORKERS', 3)
threads = _number('GUNICORN_THREADS', 4)
# A request that takes longer is cut off and its worker restarted. The proxy waits a little longer (deploy/proxy).
timeout = _number('GUNICORN_TIMEOUT', 120)
graceful_timeout = _number('GUNICORN_GRACEFUL_TIMEOUT', 30)
keepalive = 5
# A worker is replaced, in order, after this many requests (spread so that they are not all replaced at once): what a
# long-lived process gathers (memory) is given back.
max_requests = _number('GUNICORN_MAX_REQUESTS', 2000)
max_requests_jitter = max(1, max_requests // 10)
# The root file system is read-only (deploy/compose.yml): the workers' heartbeat files live in memory.
worker_tmp_dir = '/dev/shm'
# The proxy writes the access log (with the one-time link of a password mail cut out, deploy/proxy); gunicorn writes
# its own events and errors to stderr, which the container runtime keeps and rotates.
accesslog = None
errorlog = '-'
loglevel = os.environ.get('GUNICORN_LOG_LEVEL', 'info')
# The request's own size limits stay gunicorn's; the body limit is the proxy's (client_max_body_size).
proc_name = 'balik-web'
# No control socket (gunicornc): the root file system is read-only, and compose manages the container.
control_socket_disable = True


def on_starting(server):
    """The deploy check, in the master, before any worker exists: an Error or a Warning stops the server."""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    import django
    django.setup()
    from django.core.management import call_command
    from django.core.management.base import CommandError
    from django.db import connections
    try:
        call_command('check', deploy=True, fail_level='WARNING')
    except CommandError as error:
        raise SystemExit(f'The deploy check refused to start the server:\n{error}') from None
    finally:
        # The check may have opened a database connection: never let the workers inherit it (fork).
        connections.close_all()
