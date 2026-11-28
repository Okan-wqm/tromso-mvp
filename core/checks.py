import os
from urllib.parse import urlsplit

from django.conf import settings
from django.core.checks import Error, Tags, Warning, register
from django.core.checks.mail import NON_PRODUCTION_EMAIL_BACKENDS
from django.core.exceptions import ValidationError
from django.core.mail import DEFAULT_MAILER_ALIAS
from django.core.validators import validate_email
from django.http.request import validate_host

from . import catalogs

# The browser code is TypeScript compiled into static/js, which is not committed.
ENTRY_SCRIPTS = ['js/nav-boot.js', 'js/shell.js', 'js/components.js', 'js/auth.js', 'js/poll.js', 'js/windows.js',
                  'js/designer.js', 'js/announce.js', 'js/wall.js', 'js/strip.js']


def build_problems():
    """What is missing or broken of the compiled browser code: the entry scripts of static/js, and the islands' manifest
    (vite.config.mjs: missing, or there but not readable), each looked for where the server serves it (assets.built:
    STATIC_ROOT first, then the build's), so a server that serves STATIC_ROOT only is not stopped for scripts it has."""
    from .templatetags.assets import ManifestUnreadable, built, islands_manifest, manifest_path
    problems = [f'{path} is missing' for path in ENTRY_SCRIPTS if not built(path)]
    where = os.path.relpath(manifest_path(), settings.BASE_DIR).replace(os.sep, '/')
    try:
        if islands_manifest() is None:
            problems.append(f'{where} is missing')
    except ManifestUnreadable as error:
        problems.append(f'{where} cannot be read ({error.__cause__})')
    return problems


HINT = ('Run `npm ci && npm run build` (static/js, static/islands/manifest.json), then collectstatic where the server '
        'serves STATIC_ROOT.')


@register()
def compiled_scripts(app_configs, **kwargs):
    """Warns when the compiled browser code is missing or broken: the pages would load without their scripts, and a page
    with an island would fail."""
    problems = build_problems()
    if not problems:
        return []
    return [Warning(f'The compiled browser code: {"; ".join(problems)}.', hint=HINT, id='core.W001')]


@register(deploy=True)
def compiled_scripts_deployed(app_configs, **kwargs):
    """The same for a deployment (`check --deploy`): there it stops the release, as a page with an island would answer
    500."""
    problems = build_problems()
    if not problems:
        return []
    return [Error(f'The compiled browser code: {"; ".join(problems)}.', hint=HINT, id='core.E007')]


@register()
def catalogs_are_built(app_configs, **kwargs):
    """The .mo files are built, not committed, so a missing or outdated one would silently leave a
    language in English: say so when the server starts."""
    return [
        Warning(f'The {catalogs.language_name(language)} catalog is not built or is older than its .po file.',
                hint='Run `manage.py compile_catalogs`.', id='core.W002')
        for language in catalogs.languages() if not catalogs.is_built(language)
    ]


@register()
def chemcore_matches(app_configs, **kwargs):
    """The water-chemistry core must be the build chemcore/EXPECTED names: a stale or foreign core would give
    the fish's safety numbers of another formula, so it stops the server (an Error, not a warning)."""
    from farm.water import native
    return [
        Error(f'The water-chemistry core is not the expected build ({problem}).',
              hint='Rebuild the image (docker/testrunner.Dockerfile); after a change to chemcore, run '
                   'chemcore/scripts/gen_expected.sh and commit chemcore/EXPECTED.',
              id='core.E001')
        for problem in native.handshake_problems()
    ]


SMTP_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'


def _public_address_problem(must_send):
    """Why PUBLIC_BASE_URL cannot start an e-mail's link; None when it can. A server that must send is reached over
    https, at a host it answers to (ALLOWED_HOSTS)."""
    address = settings.PUBLIC_BASE_URL
    if not address:
        return 'it is not set'
    parts = urlsplit(address)
    if parts.scheme not in ('http', 'https') or not parts.hostname:
        return f'{address!r} is not an address like https://farm.example.no'
    if parts.username is not None or parts.password is not None:
        # not quoted: it may hold a password, and what stands before the @ reads as the host to a person
        return 'it holds a user part before the host'
    if parts.path or parts.query or parts.fragment:
        return f'{address!r} holds more than the scheme and the host'
    if must_send and parts.scheme != 'https':
        return f'{address!r} is not https: the link in the mail is the key to the account'
    if must_send and not validate_host(parts.hostname, settings.ALLOWED_HOSTS):
        return f'this server does not answer to {parts.hostname!r} (DJANGO_ALLOWED_HOSTS)'
    return None


@register()
def mail_is_configured(app_configs, **kwargs):
    """The account e-mails (the invitation, the password reset) must really go out: with DEBUG off (MAIL_MUST_SEND) the
    server does not start without an SMTP server, and a server that sends by SMTP, a development one too, needs a sender
    address, a public address for the links and an encrypted connection for its password. Errors, so `runserver`,
    `migrate` and `check` stop on them (README, Email)."""
    must_send = settings.MAIL_MUST_SEND
    mailer = settings.MAILERS.get(DEFAULT_MAILER_ALIAS, {})
    wrapped = [alias for alias, database in settings.DATABASES.items() if database.get('ATOMIC_REQUESTS')]
    if wrapped:
        # whatever else is set: the hand-over would happen inside the request's transaction
        return [Error(
            'ATOMIC_REQUESTS is on: a mail would be handed to the worker before the save that causes it is committed.',
            hint='Leave ATOMIC_REQUESTS off: the tabs commit their own saves, and Resource.after_commit (core.crud) '
                 'hands a mail over only after that.', id='core.E006')]
    backend = mailer.get('BACKEND', SMTP_BACKEND)
    options = mailer.get('OPTIONS', {})
    sends = bool(mailer) and backend not in NON_PRODUCTION_EMAIL_BACKENDS
    found = []
    if must_send and not (sends and (backend != SMTP_BACKEND or options.get('host'))):
        found.append(Error(
            'DEBUG is off and no SMTP server is configured (EMAIL_HOST): invitations and password resets would not be '
            'sent.',
            hint='Set EMAIL_HOST (and EMAIL_PORT, EMAIL_HOST_USER, EMAIL_HOST_PASSWORD, EMAIL_TLS as the server needs) '
                 'in the environment.', id='core.E002'))
    if not (sends or must_send):
        return found
    if sends:
        try:
            validate_email(settings.DEFAULT_FROM_EMAIL.rpartition('<')[2].rstrip('>').strip())
            unset = settings.DEFAULT_FROM_EMAIL == 'webmaster@localhost'
        except ValidationError:
            unset = True
        if unset:
            found.append(Error(
                'The sender address of the e-mails is not set, or is not an address.',
                hint='Set DEFAULT_FROM_EMAIL in the environment to an address the SMTP server may send as.',
                id='core.E003'))
    problem = _public_address_problem(must_send)
    if problem:
        found.append(Error(
            f'The public address the links in the e-mails start with (PUBLIC_BASE_URL) cannot be used: {problem}.',
            hint='Set PUBLIC_BASE_URL in the environment to the address people open the console at, scheme and host '
                 'only (https://farm.example.no).', id='core.E004'))
    if backend == SMTP_BACKEND:
        user, password = options.get('username'), options.get('password')
        if bool(user) != bool(password):
            found.append(Error(
                'The SMTP sign-in is half set: a user without a password, or a password without a user.',
                hint='Set both EMAIL_HOST_USER and EMAIL_HOST_PASSWORD, or neither.', id='core.E005'))
        elif user and not (options.get('use_tls') or options.get('use_ssl')):
            found.append(Error(
                'The SMTP password would be sent to the mail server unencrypted (EMAIL_TLS is off).',
                hint='Set EMAIL_TLS to starttls or ssl, or leave the user and the password out.', id='core.E005'))
    return found


@register(Tags.security, deploy=True)
def production_settings(app_configs, **kwargs):
    """What Django's own deploy checks do not hold a production server (DEBUG off) to (config/settings.py, the
    production block): a host list that takes every host, an http origin trusted for forms, and the activity log's
    digests under the secret key. Errors: the production server runs `check --deploy` before it starts
    (deploy/web/gunicorn.conf.py) and does not start on them."""
    if settings.DEBUG:
        return []
    found = []
    if '*' in settings.ALLOWED_HOSTS:
        found.append(Error(
            'DJANGO_ALLOWED_HOSTS holds "*": the server would answer to any host name.',
            hint='Set DJANGO_ALLOWED_HOSTS to the host names people open the console at, comma separated.',
            id='core.E007'))
    plain = [origin for origin in settings.CSRF_TRUSTED_ORIGINS
             if urlsplit(origin).scheme != 'https' or '*' in origin]
    if plain:
        found.append(Error(
            f'A form may be posted from an origin that is not https, or from every host a wildcard matches: '
            f'{", ".join(plain)}.',
            hint='Set DJANGO_CSRF_TRUSTED_ORIGINS to https origins only, each one host, or leave it unset (the public '
                 'address).',
            id='core.E008'))
    key = settings.AUDIT_DIGEST_KEY
    problem = ('it is not set, so the secret key would be used' if not key
               else 'it is the secret key' if key == settings.SECRET_KEY
               else 'it is shorter than 32 characters' if len(key) < 32 else None)
    if problem:
        found.append(Error(
            f'The activity log\'s digest key (DJANGO_AUDIT_DIGEST_KEY) cannot be used: {problem}.',
            hint='Set DJANGO_AUDIT_DIGEST_KEY (or DJANGO_AUDIT_DIGEST_KEY_FILE) to a random value of its own before '
                 'real data is written, and keep it with the backups (README, Security in the pages).',
            id='core.E009'))
    return found


@register(Tags.database)
def implied_reads(app_configs, **kwargs):
    """Roles whose Read on an area may come only from the matrix's old rule (All production or Everyone once added
    Read on save): Read and such a widening column, but no Create, Edit or Delete there. Listed for the administrator to
    review in the role matrix; nothing is changed. Run with `manage.py check --database default`."""
    from django.contrib.auth.models import Group
    from django.db import DatabaseError

    from . import access
    # Not the columns read on their own area's page (access.OWN_PAGE: Crew): Read beside one of those is needed, not left over.
    widening = [action for action, _label in access.ACTIONS
                if action not in (access.READ, *access.INCLUDES_READ, *access.OWN_PAGE)]
    found = []
    try:
        for group in Group.objects.prefetch_related('permissions__content_type').order_by('name'):
            names = {access.perm_name(permission) for permission in group.permissions.all()}
            areas = [str(area.label) for area in access.areas()
                     if area.perm(access.READ) in names
                     and any(area.perm(action) in names for action in area.actions if action in widening)
                     and not any(area.perm(action) in names for action in area.actions if action in access.INCLUDES_READ)]
            if areas:
                found.append(f'{group.name} ({", ".join(areas)})')
    except DatabaseError:
        return []
    if not found:
        return []
    return [Warning(
        f'These roles hold Read where it may come only from the old matrix rule: {"; ".join(found)}.',
        hint='Open each in Roles and untick Read where the role should only widen rows (All production, Everyone '
             'include no right of their own).', id='core.W003')]


@register(Tags.database)
def revision_triggers(app_configs, **kwargs):
    """The revision triggers (core.rev) every tracked table must have, enabled: a missing or disabled one lets a change
    pass unseen, and a stored figure built before it would be judged still valid. Named, never repaired here
    (`manage.py core_rev_repair` does it). Run with `manage.py check --database default`; quiet until core/0014
    has made the revision table."""
    from django.db import DatabaseError, connection
    from django.db.migrations.recorder import MigrationRecorder

    from . import rev
    try:
        if ('core', '0014_rev') not in MigrationRecorder(connection).applied_migrations():
            return []
        missing = rev.missing()
    except DatabaseError:
        return []
    if not missing:
        return []
    return [Warning(
        f'{len(missing)} revision trigger(s) are missing or disabled: {", ".join(missing)}. A change to their tables '
        f'moves no revision, so a stored figure could be judged valid after it.',
        hint='Run `manage.py core_rev_repair`: it makes the missing triggers again as their migrations made them and '
             'rebuilds every revision.', id='core.W005')]


def conversion_applied():
    """Whether migration core/0011 (the conversion of the log's plain values) has run on this database."""
    from django.db import connection
    from django.db.migrations.recorder import MigrationRecorder
    return ('core', '0011_private_log_values') in MigrationRecorder(connection).applied_migrations()


@register(Tags.database)
def plain_private_values(app_configs, **kwargs):
    """Plain values in the activity log under labels that were decided private (a contact's e-mail or phone, a person's
    free text): none may be there once core/0011 has run. One is there when a server still running the code from
    before wrote it after the conversion (the migration cannot know), so it is looked for here, with the conversion's
    own reading (core/migrations/_private.py). Counted, never quoted; nothing is changed. Run with `manage.py check
    --database default`; quiet until the migration has run."""
    from django.db import DatabaseError, connection

    from .migrations import _private
    try:
        if not conversion_applied():
            return []
        with connection.cursor() as cursor:
            _found, counts = _private.plan(cursor)
    except DatabaseError:
        return []
    if not counts['rows']:
        return []
    return [Warning(
        f'{counts["rows"]} activity-log row(s) hold plain values under labels that were decided private (written by a '
        f'server that still ran the code from before core/0011).',
        hint='Stop every server running the old code, then run `manage.py private_log_values --dry-run` and '
             '`manage.py private_log_values`.', id='core.W004')]


@register(Tags.database)
def invalid_indexes(app_configs, **kwargs):
    """Indexes the database keeps but cannot use: what a CREATE INDEX CONCURRENTLY or REINDEX CONCURRENTLY that failed
    part-way leaves behind (an administrator's rebuild; no migration here builds one so). Such an index is written on
    every change and never read, and a migration that makes it again stops at "already exists", so the release stops
    with it (docs/ops/upgrade.md, When it fails). One being built at this moment is invalid too until its build ends:
    it is left out (pg_stat_progress_create_index lists it). Named with the command that removes each, a partitioned
    table's index without CONCURRENTLY (PostgreSQL refuses it there); nothing is changed here. Run with `manage.py
    check --database default`."""
    from django.db import DatabaseError, connection
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT format('%I.%I', n.nspname, c.relname), c.relkind = 'I' FROM pg_index i "
                           "JOIN pg_class c ON c.oid = i.indexrelid JOIN pg_namespace n ON n.oid = c.relnamespace "
                           "WHERE NOT i.indisvalid AND NOT EXISTS (SELECT 1 FROM pg_stat_progress_create_index p "
                           "WHERE p.index_relid = i.indexrelid) ORDER BY 1")
            found = cursor.fetchall()
    except DatabaseError:
        return []
    if not found:
        return []
    return [Warning(
        f'{len(found)} index(es) are invalid, left by a concurrent build that failed: '
        f'{", ".join(name for name, _partitioned in found)}. They are never read, and a migration that makes one again '
        f'stops at "already exists".',
        hint=' '.join(f'DROP INDEX {"" if partitioned else "CONCURRENTLY "}IF EXISTS {name};'
                      for name, partitioned in found)
        + ' Then run the release again (docs/ops/upgrade.md, When it fails).', id='core.W006')]
