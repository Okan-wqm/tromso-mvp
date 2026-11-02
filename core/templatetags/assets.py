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


@register.simple_tag
def module_map():
    """An import map that sends every compiled module (static/js/*.js) to its versioned URL."""
    modules = set()
    for finder in finders.get_finders():
        for path, _ in finder.list([]):
            path = path.replace(os.sep, '/')
            if path.startswith('js/') and path.endswith('.js'):
                modules.add(path)
    imports = {static(path): versioned(path) for path in sorted(modules)}
    return mark_safe('<script type="importmap">' + json.dumps({'imports': imports}) + '</script>')
