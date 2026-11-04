from django.contrib.staticfiles import finders
from django.core.checks import Warning, register

from . import catalogs

# The browser code is TypeScript compiled into static/js, which is not committed.
ENTRY_SCRIPTS = ['js/nav-boot.js', 'js/shell.js', 'js/components.js', 'js/auth.js', 'js/poll.js']


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
