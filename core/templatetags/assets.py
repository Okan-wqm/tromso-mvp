"""Static files a browser can never serve stale.

A browser keeps CSS and scripts in its cache, so after a change a page could arrive with new markup
and old styles and scripts: text on top of text, menus that do nothing. Every asset URL therefore
carries the file's modification time, and the compiled modules get the same through an import map,
because a module's own `import './dom.js'` cannot carry a version."""
import json
import os

from django import template
from django.contrib.staticfiles import finders
from django.templatetags.static import static
from django.utils.html import format_html
from django.utils.safestring import mark_safe

register = template.Library()


def versioned(path):
    found = finders.find(path)
    if not found:
        return static(path)
    return f'{static(path)}?v={int(os.path.getmtime(found))}'


@register.simple_tag
def asset(path):
    """The static URL of `path`, versioned by the file's modification time."""
    return versioned(path)


@register.simple_tag(takes_context=True)
def module_map(context):
    """An import map that sends every compiled module (static/js/*.js) to its versioned URL. It is an inline script, so
    it carries the response's nonce (the Content-Security-Policy runs no other inline script)."""
    modules = set()
    for finder in finders.get_finders():
        for path, _ in finder.list([]):
            path = path.replace(os.sep, '/')
            if path.startswith('js/') and path.endswith('.js'):
                modules.add(path)
    imports = {static(path): versioned(path) for path in sorted(modules)}
    nonce = context.get('csp_nonce')        # lazy: made (and put in the header) by being read here
    attribute = format_html(' nonce="{}"', nonce) if nonce is not None else ''
    return mark_safe(f'<script type="importmap"{attribute}>' + json.dumps({'imports': imports}) + '</script>')
