"""Static files a browser can never serve stale.

A browser keeps CSS and scripts in its cache, so after a change a page could arrive with new markup
and old styles and scripts: text on top of text, menus that do nothing. Every asset URL therefore
changes with the file, and the compiled modules get the same through an import map, because a
module's own `import './dom.js'` cannot carry a version:

- a production server (DEBUG off) serves the names `collectstatic` gave the files, each holding a hash of its
  content (ManifestStaticFilesStorage, config/settings.py STORAGES), so the proxy lets a browser keep them for a year;
- a development server serves the plain names, each with its file's modification time (`?v=`)."""
import json
import os

from django import template
from django.conf import settings
from django.contrib.staticfiles import finders
from django.contrib.staticfiles.storage import HashedFilesMixin, staticfiles_storage
from django.templatetags.static import static
from django.utils.html import format_html
from django.utils.safestring import mark_safe

register = template.Library()


def hashed():
    """Whether the static files are served under names that carry their content's hash (a production server)."""
    return isinstance(staticfiles_storage, HashedFilesMixin)


def versioned(path):
    if hashed():
        return static(path)                 # the name is the version; a file missing from the manifest raises
    found = finders.find(path)
    if not found:
        return static(path)
    return f'{static(path)}?v={int(os.path.getmtime(found))}'


@register.simple_tag
def asset(path):
    """The static URL of `path`, versioned by the file's content hash or its modification time."""
    return versioned(path)


def modules():
    """The compiled modules (js/*.js): from the manifest `collectstatic` wrote, else from the static folders."""
    if hashed():
        return sorted(path for path in staticfiles_storage.hashed_files if path.startswith('js/') and path.endswith('.js'))
    found = set()
    for finder in finders.get_finders():
        for path, _ in finder.list([]):
            path = path.replace(os.sep, '/')
            if path.startswith('js/') and path.endswith('.js'):
                found.add(path)
    return sorted(found)


@register.simple_tag(takes_context=True)
def module_map(context):
    """An import map that sends every compiled module (static/js/*.js), by the plain address a module's own
    `import './dom.js'` resolves to, to its versioned URL. It is an inline script, so it carries the response's nonce
    (the Content-Security-Policy runs no other inline script)."""
    imports = {f'{settings.STATIC_URL}{path}': versioned(path) for path in modules()}
    nonce = context.get('csp_nonce')        # lazy: made (and put in the header) by being read here
    attribute = format_html(' nonce="{}"', nonce) if nonce is not None else ''
    return mark_safe(f'<script type="importmap"{attribute}>' + json.dumps({'imports': imports}) + '</script>')
