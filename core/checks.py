from django.contrib.staticfiles import finders
from django.core.checks import Tags, Warning, register

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


@register(Tags.database)
def implied_reads(app_configs, **kwargs):
    """Roles whose Read on an area may come only from the matrix's old rule (Crew, All production or Everyone once added
    Read on save): Read and a widening column, but no Create, Edit or Delete there. Listed for the administrator to
    review in the role matrix; nothing is changed. Run with `manage.py check --database default`."""
    from django.contrib.auth.models import Group
    from django.db import DatabaseError

    from . import access
    widening = [action for action, _label in access.ACTIONS if action not in (access.READ, *access.INCLUDES_READ)]
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
        hint='Open each in Roles and untick Read where the role should only widen rows (Crew, All production, Everyone '
             'include no right of their own).', id='core.W003')]
