"""Static files a browser can never serve stale, and the islands' entry points.

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


# ---- Islands (README, Frontend: islands): a React root a server-rendered page mounts, built by Vite into static/islands
# (vite.config.mjs). The build's manifest maps an island's name to its hashed file and the chunks it imports; it is read
# once per server start (and again whenever the file changes, so a build during development is seen without a restart).

MANIFEST = 'islands/manifest.json'


def manifest_path():
    """Where the islands' manifest is read: settings.ISLANDS_MANIFEST when set (the tests' fixture); else the collected
    static files' (STATIC_ROOT/islands/manifest.json, a production server that serves STATIC_ROOT only), when there is
    one; else the build's, static/islands/manifest.json (npm run build, found by the static finders). It is a plain file
    name, no dot-folder: collectstatic copies it with the islands."""
    from django.conf import settings
    if getattr(settings, 'ISLANDS_MANIFEST', None):
        return settings.ISLANDS_MANIFEST
    return built(MANIFEST) or os.path.join(settings.BASE_DIR, 'static', *MANIFEST.split('/'))


def built(path):
    """Where the server serves the built static file `path` (under static/): the collected one (STATIC_ROOT/<path>, a
    production server that serves STATIC_ROOT only) when there is one, else the build's, found by the static finders;
    None when it is in neither. The one answer for the islands' manifest and the entry scripts (core.W001, core.E007),
    so a STATIC_ROOT-only server is never told its scripts are missing."""
    from django.conf import settings
    from django.contrib.staticfiles import finders
    root = getattr(settings, 'STATIC_ROOT', None)
    if root and os.path.exists(os.path.join(root, *path.split('/'))):
        return os.path.join(root, *path.split('/'))
    return finders.find(path)


class ManifestUnreadable(Exception):
    """The manifest is there but is not a manifest (cut short, not JSON, not Vite's shape)."""


_manifest_cache = {}


def islands_manifest():
    """{island name: {'file': path under static/islands, 'imports': [...], 'css': [...]}} of the build's manifest ({} for
    a build without islands); None when there is no build (core.W001 says so, and core.E007 under
    `check --deploy`). A
    manifest that cannot be read raises ManifestUnreadable (the checks report it; a page with an island fails loudly)."""
    path = manifest_path()
    try:
        stamp = os.path.getmtime(path)
    except OSError:
        return None
    cached = _manifest_cache.get(path)
    if cached and cached[0] == stamp:
        return cached[1]
    try:
        with open(path, encoding='utf-8') as handle:
            raw = json.load(handle)
        if not isinstance(raw, dict):
            raise ValueError('not an object')
        islands = {}
        for key, chunk in raw.items():
            if chunk.get('isEntry'):
                name = chunk.get('name') or os.path.splitext(os.path.basename(key))[0]
                files, css = _imports(raw, key)
                islands[name] = {'file': chunk['file'], 'imports': files, 'css': list(dict.fromkeys([*chunk.get('css', []), *css]))}
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        raise ManifestUnreadable(f'{path}: {error}') from error
    _manifest_cache[path] = (stamp, islands)
    return islands


def _imports(raw, key):
    """([the files `key` imports], [their stylesheets]), at any depth, depth first, each once: the browser preloads the
    files beside the island and the page links every stylesheet one of them brings (uPlot's, two chunks deep)."""
    files, css, seen = [], [], set()

    def walk(at):
        for child in raw[at].get('imports', []):
            if child in seen:
                continue
            seen.add(child)
            files.append(raw[child]['file'])
            css.extend(raw[child].get('css', []))
            walk(child)

    walk(key)
    return files, css


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
