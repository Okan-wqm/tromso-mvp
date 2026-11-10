from django.contrib.staticfiles import finders
from django.core.checks import Error, Tags, Warning, register

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
