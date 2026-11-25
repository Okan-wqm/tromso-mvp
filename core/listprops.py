"""The props of the new look's list page (island `list-page`, frontend/islands/ui/ListPage.tsx), drawn behind `?ui=next` by
the one list view (core.crud.ListView): the toolbar (search and filters as one GET form, so the server reads the address
and stays the only source of what is listed), the link tabs of a tab's views, its notices, the table with each row's
actions, the empty state and the pager. Every word is the classic page's own msgid (crud/list.html, crud/_pager.html and
the tab's list template), so the new page says nothing the old one did not; core.pagesays holds each page to its old one.

A tab draws its list here by giving `Resource.list_rows(view, objects, context)`: the columns and the rows of its table
(built with `column`, `cell`, `chip`, `link`, `post` and `row` below) and, if it has them, its tabs, notices and lines.
Its filters are `Resource.list_filters(view, context)` (`choice`). A tab without `list_rows` keeps its classic list in the
new look as well.

Row titles and actions are the records' own addresses: in the new look they open the record form page, not a dialog."""
from pathlib import Path

from django.conf import settings
from django.middleware.csrf import get_token
from django.utils.translation import gettext as _

from . import ui

ICONS = Path(settings.BASE_DIR) / 'templates' / 'icons'
TONES = {'critical', 'warning', 'ok', 'neutral'}
STATUS_CHIP = {'active': 'ok', 'inactive': 'neutral'}     # a record's Active / Inactive as its chip
CHIPS = {'ok', 'warning', 'critical', 'hold', 'neutral', 'note', 'accent', 'stale', 'nodata'}


def _icon(name):
    """An icon of the one set (templates/icons): a name the island cannot draw is refused here, not drawn blank."""
    if not (ICONS / f'{name}.svg').is_file():
        raise ValueError(f'no icon {name!r} in templates/icons')
    return name


def column(key, label, numeric=False):
    return {'key': key, 'label': str(label), 'numeric': bool(numeric)}


def chip(kind, text):
    if kind not in CHIPS:
        raise ValueError(f'no chip kind {kind!r}')
    return {'kind': kind, 'text': str(text)}


def cell(text=None, *, href=None, strong=False, sub=(), chip=None, chips=(), gauge=None, details=None, pips=None):
    """One cell: its text (a link to `href`), a sub-line per item of `sub` (empty items left out), or a `chip`; a `gauge`
    (below) is drawn under the text; `details` (below) is drawn in place of the text, closed; `pips` (below) before it."""
    said = {'text': None if text is None else str(text), 'href': href or None, 'strong': bool(strong),
            'chip': chip, 'chips': list(chips), 'sub': [str(item) for item in sub if item not in (None, '')]}
    if gauge is not None:
        said['gauge'] = gauge
    if details is not None:
        said['details'] = details
    if pips is not None:
        said['pips'] = pips
    return said


PIP_STATES = {'done', 'next', ''}


def pips(states, label):
    """A day's meals as pips (frontend/islands/ui/Pips.tsx, the classic .ui-pips): one state per planned meal, 'done',
    'next' or '' (to come), as farm.templatetags.feeding.meal_pips gives them, and `label` their words ("2 of 4 meals
    done"): the pips are never the only cue."""
    states = [str(state) for state in states]
    if not set(states) <= PIP_STATES:
        raise ValueError(f'no pip state in {states!r}')
    return {'states': states, 'label': str(label)}


def gauge(share, text, status=None):
    """A share of a whole as a bar and in words (frontend/islands/ui/Gauge.tsx): `share` in % (None is 0; the bar is full
    from 100), `text` the share said ("12 % of capacity": the bar is never the only cue), `status` critical or warning."""
    if status not in (None, 'critical', 'warning'):
        raise ValueError(f'no gauge status {status!r}')
    value = 0.0 if share in (None, '') else max(0.0, min(float(share), 100.0))
    return {'value': round(value, 1), 'text': str(text), 'status': status}


def link(href, label, icon, danger=False, labelled=False):
    """A row action that opens a page (the record's edit, its delete confirmation); `labelled` draws its word beside the
    icon (the meal board's Record meal, a record's Void)."""
    said = {'kind': 'link', 'href': href, 'label': str(label), 'icon': _icon(icon), 'danger': bool(danger)}
    if labelled:
        said['labelled'] = True
    return said


def post(href, label, icon, fields=(), danger=False, labelled=False):
    """A row action that posts at once (with the page's CSRF token), as the classic page's small form does; `labelled`
    draws its word beside the icon (an action that changes a safety state: Acknowledge, Resolve)."""
    said = {'kind': 'post', 'href': href, 'label': str(label), 'icon': _icon(icon), 'danger': bool(danger),
            'fields': [{'name': name, 'value': str(value)} for name, value in fields]}
    if labelled:
        said['labelled'] = True
    return said


def details(summary, lines):
    """A cell's closed disclosure: its summary, and its lines (empty ones left out) shown when it is opened."""
    return {'summary': str(summary), 'lines': [str(line) for line in lines if line not in (None, '')]}


def row(key, cells, actions=(), status=None, voided=False):
    return {'key': str(key), 'status': status, 'voided': bool(voided), 'cells': cells, 'actions': list(actions)}


def group(key, title, rows, chips=(), meta=None):
    """A group of a list's rows, drawn as a plate of its own with its own table of the shared columns (ListPage.tsx
    `groups`): its title, chips beside it, a meta line, and the keys of its rows (each a `row` of the table)."""
    return {'key': str(key), 'title': str(title), 'chips': list(chips), 'meta': None if meta is None else str(meta),
            'rows': [str(each) for each in rows]}


def choice(name, label, chosen, options, groups=()):
    """A filter: a select named `name` (its label for a screen reader), `options` as (value, label) pairs (the first is
    "All …"), `groups` as (group label, options) for options under a heading (an empty group left out)."""
    pairs = lambda each: [{'value': str(value), 'label': str(text)} for value, text in each]   # noqa: E731
    return {'kind': 'select', 'name': name, 'label': str(label), 'value': str(chosen or ''), 'options': pairs(options),
            'groups': [{'label': str(group), 'options': pairs(items)} for group, items in groups if items]}


def day(name, label, value):
    """A filter of one day, typed the European way: the box core.widgets.DayInput draws, with its example."""
    from django.utils import formats
    from .widgets import EXAMPLE
    return {'kind': 'day', 'name': name, 'label': str(label), 'value': formats.localize_input(value) if value else '',
            'placeholder': formats.localize_input(EXAMPLE.date()), 'options': [], 'groups': []}


def check(name, label, checked):
    """A filter that is on or off: a check box named `name` sending 1 when it is ticked ("Show voided")."""
    return {'kind': 'check', 'name': name, 'label': str(label), 'value': '1' if checked else '', 'options': [],
            'groups': []}


def tabs(label, items):
    """Link tabs: (href, label, count or None, current) for each view of the list."""
    return {'label': str(label), 'tabs': [{'href': href, 'label': str(text), **({'count': str(count)} if count is not None
                                                                              else {}), 'current': bool(current)}
                                          for href, text, count, current in items]}


def notice(key, tone, text, link=None):
    """A sentence above the table in its tone; `link` (href, label) ends it with a link ("Show them")."""
    if tone not in TONES:
        raise ValueError(f'no notice tone {tone!r}')
    said = {'key': key, 'tone': tone, 'text': str(text)}
    if link is not None:
        said['link'] = {'href': link[0], 'label': str(link[1])}
    return said


def pager(page, pager_query):
    """The pager of a list page (crud/_pager.html's words): None for one page; else the range, the page and the
    previous/next links, each keeping the query (`pager_query`, without page=). Every list-page island's props use it: a
    tab's (list_props) and a page's that is not a tab (sensors/pages.py)."""
    if page is None or page.paginator.num_pages <= 1:
        return None
    at = f'?{pager_query}&page=' if pager_query else '?page='
    return {
        'label': _('Pages'),
        'range': _('%(first)s–%(last)s of %(total)s') % {'first': page.start_index(), 'last': page.end_index(),
                                                         'total': page.paginator.count},
        'page': _('Page %(number)s of %(total)s') % {'number': page.number, 'total': page.paginator.num_pages},
        'previous': {'href': f'{at}{page.previous_page_number()}', 'label': _('Previous')} if page.has_previous() else None,
        'next': {'href': f'{at}{page.next_page_number()}', 'label': _('Next')} if page.has_next() else None,
    }


_pager = pager     # the earlier private name, kept for branches that still call it


def page_props(request, *, label, columns, rows, filters=(), notices=(), empty, page=None, pager_query='', groups=None,
               tabs=None, lines=(), add=None, keep=(), table_label=None):
    """The list-page island's props of a page that is not a tab (`list_props` is a tab's): its link tabs (`tabs`), filters
    (a GET form, `filters` as `choice`, `day`, `check`; what else the address holds is sent again, and `keep` (name,
    value) whatever it says), its Add link (`add`: (href, label)), notices, lines above the table, the table (in `groups`
    when given; `table_label` its accessible name, else `label`), what is said when there is no row (`empty`: a title, or
    the whole {title, text, link, add}), and the pager."""
    shown = {each['name'] for each in filters} | {key for key, _value in keep} | {'page', ui.PARAM}
    return {
        'csrfToken': get_token(request),
        'tabs': tabs,
        'toolbar': {'label': str(label), 'search': None,
                    'keep': [*({'name': key, 'value': str(value)} for key, value in keep),
                             *({'name': key, 'value': value} for key, value in request.GET.items() if key not in shown)],
                    'filters': list(filters), 'submit': _('Filter'),
                    'add': {'href': add[0], 'label': str(add[1])} if add else None},
        'notices': list(notices),
        'lines': [str(line) for line in lines if line],
        'table': {'label': str(table_label or label), 'columns': columns, 'rows': rows, 'actionsLabel': _('Actions')},
        'groups': groups,
        'empty': empty if isinstance(empty, dict) else {'title': str(empty), 'text': None, 'link': None, 'add': None},
        'pager': pager(page, pager_query),
    }


def toolbar(view, context, filters, keep=()):
    """A list's toolbar (ListPage's ListToolbar): the search, `filters` (choice, day) and what the address holds besides
    them sent again (a view, a tab; `keep`: (name, value) the form must send whatever the address says, a week), and the
    Add link. The classic list's words (crud/list.html)."""
    r, request = view.resource, view.request
    plural, name = r.plural, r.name
    shown = {'q', 'page', ui.PARAM, *(each['name'] for each in filters), *(key for key, _value in keep)}
    search = _('Search %(plural)s') % {'plural': plural}
    return {
        'label': search,
        'search': {'name': 'q', 'value': context.get('query', ''), 'label': search,
                   'placeholder': str(r.search_placeholder) if r.search_placeholder else search},
        'keep': [*({'name': key, 'value': str(value)} for key, value in keep),
                 *({'name': key, 'value': value} for key, value in request.GET.items() if key not in shown)],
        'filters': filters, 'submit': _('Filter'),
        'add': {'href': context['create_url'], 'label': _('Add %(name)s') % {'name': name}} if context.get('can_add') else None,
    }


def empty(view, context):
    """What an empty list says (crud/list.html): none matching the search with the way back, or none yet with what to do."""
    r, query = view.resource, context.get('query', '')
    if query:
        return {'title': _('No %(plural)s match “%(query)s”') % {'plural': r.plural, 'query': query},
                'text': _('Try another search.'),
                'link': {'href': context['list_url'], 'label': _('Show all %(plural)s') % {'plural': r.plural}}, 'add': None}
    return {'title': _('No %(plural)s yet') % {'plural': r.plural},
            'text': str(r.empty_text) if r.empty_text else _('Add the first %(name)s.') % {'name': r.name},
            'link': None,
            'add': {'href': context['create_url'], 'label': _('Add %(name)s') % {'name': r.name}} if context.get('can_add') else None}


def list_props(view, objects, context):
    """Everything the list-page island draws for `view` (a core.crud.ListView) over the rows it read (`objects`, this
    page's) and the context the classic page gets (`context`: query, page, pager_query and the tab's filter values)."""
    r, request = view.resource, view.request
    table = r.list_rows(view, objects, context)
    return {
        'csrfToken': get_token(request),
        'tabs': table.get('tabs'),
        'toolbar': toolbar(view, context, r.list_filters(view, context)),
        'notices': table.get('notices', []),
        'lines': [str(line) for line in table.get('lines', ())],
        'table': {'label': str(r.title(view.mount)), 'columns': table['columns'], 'rows': table['rows'],
                  'actionsLabel': _('Actions')},
        'timeline': table.get('timeline'),
        'empty': empty(view, context),
        'pager': pager(context.get('page'), context.get('pager_query', '')),
    }


def title(view, context, obj, text, sub=()):
    """The first cell of a tab's row: the record's name, a link to its edit page when the person may edit it (its own
    page in the new look), and its sub-lines."""
    editable = context.get('can_change') and view.resource.allowed(view.request, obj, 'change')
    return cell(text, href=view.url('edit', obj.pk) if editable else None, strong=True, sub=sub)


def edit_delete(view, context, obj, name):
    """A row's Edit and Delete, each only for a person who may (the classic list's pencil and bin): the record's edit
    page and its delete confirmation."""
    r, request = view.resource, view.request
    actions = []
    if context.get('can_change') and r.allowed(request, obj, 'change'):
        actions.append(link(view.url('edit', obj.pk), _('Edit %(name)s') % {'name': name}, 'pencil'))
    if context.get('can_delete') and r.allowed(request, obj, 'delete'):
        actions.append(link(view.url('delete', obj.pk), _('Delete %(name)s') % {'name': name}, 'trash', danger=True))
    return actions
