from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.staticfiles import finders
from django.core.checks import Error, Tags, Warning, register
from django.core.checks.mail import NON_PRODUCTION_EMAIL_BACKENDS
from django.core.exceptions import ValidationError
from django.core.mail import DEFAULT_MAILER_ALIAS
from django.core.validators import validate_email
from django.http.request import validate_host

from . import catalogs

# The browser code is TypeScript compiled into static/js, which is not committed.
ENTRY_SCRIPTS = ['js/nav-boot.js', 'js/shell.js', 'js/components.js', 'js/auth.js', 'js/poll.js', 'js/windows.js',
                  'js/designer.js', 'js/announce.js']


@register()
def compiled_scripts(app_configs, **kwargs):
    """Warns when the compiled browser code is missing: the pages would load without their scripts."""
    missing = [path for path in ENTRY_SCRIPTS if not finders.find(path)]
    if not missing:
        return []
    return [Warning(
        f'The compiled browser code is missing ({", ".join(missing)}).',
        hint='Run `npm install && npm run build` to compile frontend/*.ts into static/js.',
        id='core.W001',
    )]


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
