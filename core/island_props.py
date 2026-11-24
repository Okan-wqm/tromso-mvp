"""The props a page gives its island, read in a test: the one way a test renders a view's island and keeps its props for the
browser tests (frontend/test/*.pages.ts). The props are made in the TEST database, from the tests' own fixtures, through
the real views, inside the test run, and written under .build/island-props/ (not committed): the repository is public,
so nothing recorded from a real database is ever kept (owner's privacy rule, 2026-11-24).

    props = render_island(client, url, 'water', query={'range': '7d'}, language='nb')
    keep('water-nb', props)                     # .build/island-props/water-nb.json, read by the browser test

The view is asked in the new look (`?ui=next`, core/ui.py), in the language given (the account's language wins over the
cookie, core/language.py, so both are set); the island's root must be there exactly once, and its props are returned as
the page wrote them (json_script, `{% island %}` in core/templatetags/assets.py)."""
import json
import re
from pathlib import Path

from django.conf import settings

from . import ui

OUT = Path(settings.BASE_DIR) / '.build' / 'island-props'


def props_of(html, island):
    """The props of the first root of `island` in a page's HTML; AssertionError when the page has none or several."""
    roots = re.findall(rf'data-island="{re.escape(island)}" data-props="([\w-]+)"', html)
    if len(roots) != 1:
        raise AssertionError(f'{len(roots)} roots of island {island!r} on the page, one expected')
    found = re.search(rf'<script id="{re.escape(roots[0])}" type="application/json">(.*?)</script>', html, re.S)
    if found is None:
        raise AssertionError(f'the props block {roots[0]} of island {island!r} is missing')
    return json.loads(found.group(1))


def render_island(client, url, island, query=None, language=None):
    """The props `url` gives `island` in the new look, for the signed-in person of `client` (in `language`, if given)."""
    if language is not None:
        from core.language import save_account_language

        user = client.session.get('_auth_user_id')
        if user is not None:
            from django.contrib.auth import get_user_model
            save_account_language(get_user_model().objects.get(pk=user), language)
        client.cookies[settings.LANGUAGE_COOKIE_NAME] = language
    response = client.get(url, {**(query or {}), ui.PARAM: ui.NEXT})
    if response.status_code != 200:
        raise AssertionError(f'{url} answered {response.status_code} in the new look')
    return props_of(response.content.decode(), island)


def keep(name, props):
    """Writes the props for the browser tests: .build/island-props/<name>.json. Returns the path."""
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f'{name}.json'
    path.write_text(json.dumps(props, ensure_ascii=False, indent=1), encoding='utf-8')
    return path
