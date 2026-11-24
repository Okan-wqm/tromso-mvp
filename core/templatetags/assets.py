"""Static files a browser can never serve stale, and the islands' entry points.

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


# ---- Islands (README, Frontend: islands): a React root a server-rendered page mounts, built by Vite into static/islands
# (vite.config.mjs). The build's manifest maps an island's name to its hashed file and the chunks it imports; it is read
# once per server start (and again whenever the file changes, so a build during development is seen without a restart).

def manifest_path():
    from django.conf import settings
    return getattr(settings, 'ISLANDS_MANIFEST', None) or os.path.join(settings.BASE_DIR, 'static', 'islands', '.vite',
                                                                       'manifest.json')


_manifest_cache = {}


def islands_manifest():
    """{island name: {'file': path under static/islands, 'imports': [...], 'css': [...]}} of the build's manifest ({} for
    a build without islands); None when there is no build (core.W001 says so)."""
    path = manifest_path()
    try:
        stamp = os.path.getmtime(path)
    except OSError:
        return None
    cached = _manifest_cache.get(path)
    if cached and cached[0] == stamp:
        return cached[1]
    with open(path, encoding='utf-8') as handle:
        raw = json.load(handle)

    def chunk_files(key, seen):
        """The files `key` imports, depth first, each once (the browser preloads them beside the island)."""
        found = []
        for child in raw.get(key, {}).get('imports', []):
            if child not in seen:
                seen.add(child)
                found += [raw[child]['file'], *chunk_files(child, seen)]
        return found

    islands = {}
    for key, chunk in raw.items():
        if chunk.get('isEntry'):
            name = chunk.get('name') or os.path.splitext(os.path.basename(key))[0]
            css = [*chunk.get('css', []), *(c for child in raw.get(key, {}).get('imports', []) for c in raw.get(child, {}).get('css', []))]
            islands[name] = {'file': chunk['file'], 'imports': chunk_files(key, set()), 'css': list(dict.fromkeys(css))}
    _manifest_cache[path] = (stamp, islands)
    return islands


class UnknownIsland(Exception):
    pass


@register.simple_tag(takes_context=True)
def island(context, name, props=None, label=''):
    """One island: its root (a <div data-island> holding what is shown until the script draws, `label` in words), its
    props as a JSON data block (json_script: escaped, never run as a script, so the Content-Security-Policy is
    untouched), and, once per page, its module and the chunks it imports. Only finished values travel in the props:
    the server reads, judges and words them; the island draws them.
        {% island "gallery" props label=_("Loading the gallery…") %}"""
    from django.templatetags.static import static as static_url
    from django.utils.html import json_script

    entry = (islands_manifest() or {}).get(name)
    if entry is None:
        # A page without its island would show its placeholder for ever: it fails loudly (core.W001 warns at start).
        raise UnknownIsland(f'No island named {name!r} in {manifest_path()}: run `npm run build`.')
    counter = context.render_context.setdefault('islands', {'count': 0, 'loaded': set()})
    counter['count'] += 1
    props_id = f'island-{name}-{counter["count"]}'
    parts = [format_html('<div class="ui-island" data-island="{}" data-props="{}">{}</div>', name, props_id,
                         format_html('<p class="ui-loading" role="status">{}</p>', label) if label else ''),
             json_script(props if props is not None else {}, props_id)]
    if name not in counter['loaded']:
        counter['loaded'].add(name)
        prefix = 'islands/'
        parts += [format_html('<link rel="stylesheet" href="{}">', static_url(prefix + css)) for css in entry['css']]
        parts += [format_html('<link rel="modulepreload" href="{}">', static_url(prefix + chunk)) for chunk in entry['imports']]
        parts.append(format_html('<script type="module" src="{}"></script>', static_url(prefix + entry['file'])))
    return mark_safe(''.join(parts))
