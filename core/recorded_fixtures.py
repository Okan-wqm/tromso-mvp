"""The browser tests' recorded fixtures, rendered from the TEST WORLD (core/test_world.py) by the one function both their
recorder (scripts/record_test_world.py, which writes them) and their freshness test (core/tests_fixtures_fresh.py, which
compares them with what the code renders today) call: `render_all(admin)`, {path under frontend/test/pages: text}.

    form-oracle.json                    every visible field of every tab's form (new, sent empty, editing a record of the
                                        test world, the rows of its row lists), with the controls the server's own field
                                        template draws for it (core/tests_formpayload.py's reading), and the handling
                                        acknowledgement
    company-props-<language>.json       Company › Overview's props (config/company_props.py) in en, nb, tr
    list-props-<language>.json          the list pages' props (core/listprops.py) in en, nb, tr
    panel-props-<language>.json         the same of the production panel's list pages
    panel/<page>-<language>.html        the production panel's pages drawn by the server (Tasks with its drawer, Regulatory
                                        reports, Storage, Messages), whole, in the new look

Call it with the clock pinned to MOMENT and the language English, after `world(admin)` (built on core.test_world.ticking). A person offered in a list of
people or roles is written `user:<user name>`, `role:<name>`, not by the id the database counted (as a session's token is written test-token).
What varies from one rendering to the next (record ids, a page's nonce and token, the assets' versions, the islands'
build names) is not the fixture's content: `normalised` puts it in a fixed form, and `first_difference` says where
two renderings part."""
import json
import re

# The list pages drawn by the list-page island (core/listprops.py) whose props are recorded: {name: address}.
LISTS = {
    'team': 'hr:employee_list', 'team-production': 'hr:production_employee_list',
    'departments': 'hr:officedepartment_list', 'attendance': 'hr:attendancerecord_list',
    'leave': 'hr:leaverequest_list', 'leave-all': 'hr:leaverequest_list?tab=all', 'shifts': 'hr:shift_list',
    'holidays': 'hr:holiday_list', 'leave-types': 'hr:leavetype_list',
}
# The production panel's list pages (core/test_world.py panel_world), recorded to panel-props-<language>.json.
PANEL_LISTS = {
    'recurring-tasks': 'tasks:taskseries_list', 'questions': 'reports:openquestion_list',
    'experiments': 'experiments:experiment_list', 'experiments-mine': 'experiments:experiment_list?view=mine',
    'experiments-templates': 'experiments:experiment_list?view=templates',
}
LANGUAGES = ('en', 'nb', 'tr')


def _first_record(resource):
    """The record of a tab whose edit form is recorded: the first by its words, never by its random id."""
    records = list(resource.queryset())
    return min(records, key=lambda record: (str(record), str(record.pk))) if records else None


def cases_of(admin):
    """([{case, field, controls}] of every tab's forms in the test world, [tabs with no record to edit])."""
    from django import forms
    from django.test import RequestFactory

    from core.crud import Resource
    from core.formpayload import UnknownWidget, field_payload, unshown_visible_fields
    from core.formprops import DRAWN
    from core.tests_formpayload import drawn

    def request():
        made = RequestFactory().get('/')
        made.user = admin
        made.session = {}
        return made

    def fields(label, form):
        found = []
        for bound in form:
            if bound.is_hidden or bound.name in unshown_visible_fields(form):
                continue
            try:
                payload = field_payload(bound)
            except UnknownWidget:
                continue
            if payload['widget']['kind'] in DRAWN:
                found.append({'case': f'{label} {bound.name}', 'field': payload, 'controls': drawn(bound).controls})
        return found
    cases, missing = [], []
    for resource in Resource.registry:
        if resource.form_class is None:
            continue
        if resource.allows('add'):
            cases += fields(f'{resource.__name__} new', resource.form(request()))
            sent = resource.form(request(), {}, {})
            sent.is_valid()
            cases += fields(f'{resource.__name__} sent empty', sent)
        record = _first_record(resource) if resource.allows('change') else None
        if record is None:
            missing.append(resource.__name__)
            continue
        cases += fields(f'{resource.__name__} edit', resource.form(request(), instance=record))
        for key, formset in resource.edit_extras(request(), record).items():
            if isinstance(formset, forms.BaseFormSet):
                for index, row in enumerate([*formset.forms, formset.empty_form]):
                    cases += fields(f'{resource.__name__} rows {key} {index}', row)
    from farm.forms.stock import handling_ack_field

    class Acknowledged(forms.Form):
        go_on = handling_ack_field('harvest')
    acknowledged = Acknowledged()
    acknowledged.fields['go_on'].widget.fingerprint = 'f00d'
    cases += fields('handling acknowledgement', acknowledged)
    return cases, missing


def _people_case(case, people):
    """A case of a field that offers people or roles (an option whose value is an id and whose label its name), with that
    id written `user:<user name>` or `role:<name>` wherever the case holds it: its options, its value, its controls."""
    def options(value):
        if isinstance(value, dict):
            if 'value' in value and 'label' in value and isinstance(value['value'], str):
                yield value
            for item in value.values():
                yield from options(item)
        elif isinstance(value, list):
            for item in value:
                yield from options(item)
    named = {}
    for option in options(case['field']):
        stable = _named(people, option['value'], option['label'])
        if stable is not None:
            named[option['value']] = stable
    if not named:
        return case

    def renamed(value):
        if isinstance(value, str):
            return named.get(value, value)
        if isinstance(value, list):
            return [renamed(item) for item in value]
        if isinstance(value, dict):
            return {key: renamed(item) for key, item in value.items()}
        return value
    return renamed(case)


def oracle(admin):
    """({'cases': the distinct cases}, [tabs with no record to edit])."""
    cases, missing = cases_of(admin)
    people = _people()
    cases = [_people_case(case, people) for case in cases]
    seen, unique = set(), []
    for case in cases:
        key = json.dumps([case['field'], case['controls']], sort_keys=True)
        if key not in seen:
            seen.add(key)
            unique.append(case)
    return {'cases': unique}, missing


def _client(admin):
    from django.test import Client
    client = Client(HTTP_HOST='localhost')
    client.force_login(admin)
    return client


def list_props(admin, lists=LISTS):
    """{language: {name: the list-page island's props}} of every list in `lists`, as the test world's admin sees it."""
    from django.urls import reverse
    client = _client(admin)
    found = {}
    for language in LANGUAGES:
        client.cookies['django_language'] = language
        pages = {}
        for name, route in lists.items():
            url, _sep, query = route.partition('?')
            html = client.get(f'{reverse(url)}?{query}&ui=next' if query else f'{reverse(url)}?ui=next').content.decode()
            block = re.search(r'<script id="island-list-page-1" type="application/json">(.*?)</script>', html, re.S)
            if block is None:
                raise LookupError(f'{route} has no list-page island')
            pages[name] = json.loads(block.group(1))
            pages[name]['csrfToken'] = 'test-token'          # a session's token is no fixture
        found[language] = pages
    return found


def panel_pages():
    """{name: address} of the production panel's pages the server draws in the new look (core/tests_panel_next.py holds
    them to their classic pages; frontend/test/panelpages.browser.test.ts lays them out in a browser)."""
    from django.urls import reverse
    from messaging.models import Conversation
    from tasks.models import Task
    late = Task.objects.get(title='Test net check')
    storage = reverse('inventory:storage')
    return {'tasks': f"{reverse('tasks:task_list')}?task={late.pk}", 'reports': reverse('reports:report_list'),
            'storage': storage, 'storage-movements': f'{storage}?tab=movements&voided=1',
            'messages-long': reverse('messaging:conversation',
                                     args=[Conversation.objects.get(name='Test long channel').pk])}


def panel_html(admin):
    """{'<page>-<language>': the server's answer} of every page of panel_pages() in the new look, in en, nb and tr: a
    session's token replaced by a fixed word, nothing else changed."""
    client = _client(admin)
    client.cookies['ui'] = 'next'
    found = {}
    for language in LANGUAGES:
        client.cookies['django_language'] = language
        for name, address in panel_pages().items():
            html = client.get(address).content.decode()
            found[f'{name}-{language}'] = re.sub(r'(name="csrfmiddlewaretoken" value=")[^"]+',
                                                 lambda match: match.group(1) + 'test-token', html)
    return found


def _people():
    """{an id: [(kind, the names a page or a form calls it by)]} of the people and the roles: their ids are numbers the
    database counts on, so they differ from one test database to the next."""
    from django.contrib.auth import get_user_model
    from django.contrib.auth.models import Group

    from core.people import person_name
    found = {}
    for user in get_user_model().objects.all():
        names = {user.get_username(), user.get_full_name(), str(user), person_name(user)} - {''}
        found.setdefault(str(user.pk), []).append(('user', names, user.get_username()))
    for group in Group.objects.all():
        found.setdefault(str(group.pk), []).append(('role', {group.name}, group.name))
    return found


def _named(people, number, label):
    """`user:<user name>` or `role:<name>` for an id offered under its own name; None for any other number."""
    for kind, names, name in people.get(number, ()):
        if label in names:
            return f'{kind}:{name}'
    return None


_OPTION = re.compile(r'<option value="(\d+)"([^>]*)>([^<]*)</option>')
_CHOICE = re.compile(r'"value": "(\d+)"([^{}]*?)"label": "([^"]*)"')     # a value and its label, in one object


def _stable_people(text, people):
    """A person or a role offered in a list (an option, a choice of a form) by its name instead of its id, where the
    label is its name: `user:<user name>`, `role:<name>`. Other numbers stay as they are."""
    def named(number, label, whole, start, end):
        stable = _named(people, number, label)
        return whole if stable is None else whole[:start] + stable + whole[end:]

    def option(match):
        return named(match.group(1), match.group(3), match.group(0), match.start(1) - match.start(0),
                     match.end(1) - match.start(0))

    def choice(match):
        return named(match.group(1), match.group(3), match.group(0), match.start(1) - match.start(0),
                     match.end(1) - match.start(0))
    return _CHOICE.sub(choice, _OPTION.sub(option, text))


def _json(value, indent=1):
    return json.dumps(value, ensure_ascii=False, indent=indent) + ('\n' if indent else '')


def render_all(admin):
    """({path under frontend/test/pages: its text}, [tabs with no record to edit]) of every recorded fixture."""
    from django.utils import translation

    from config.company_props import overview_props
    from core.test_world import MOMENT
    texts = {}
    people = _people()
    cases, missing = oracle(admin)
    texts['form-oracle.json'] = _json(cases, indent=None)
    for language in LANGUAGES:
        with translation.override(language):
            texts[f'company-props-{language}.json'] = _json(overview_props(admin, MOMENT))
    for name, lists in (('list', LISTS), ('panel', PANEL_LISTS)):
        for language, pages in list_props(admin, lists).items():
            texts[f'{name}-props-{language}.json'] = _json(pages)
    for page, html in panel_html(admin).items():
        texts[f'panel/{page}.html'] = html
    return {name: _stable_people(text, people) for name, text in texts.items()}, missing


# What varies from one rendering to the next, never the fixture's content: (pattern, what it becomes).
_VARIES = (
    (re.compile(r'nonce="[^"]*"'), 'nonce="N"'),
    (re.compile(r"'nonce-[^']*'"), "'nonce-N'"),
    (re.compile(r'(name="csrfmiddlewaretoken" value=")[^"]*'), r'\1T'),
    (re.compile(r'("csrfToken": ")[^"]*'), r'\1T'),
    (re.compile(r'\?v=\d+'), '?v=V'),                                   # an asset's version: its file's time
    (re.compile(r'/static/islands/[^"\'\s]+'), '/static/islands/I'),    # a build's file names
    (re.compile(r'(?<=/)\d+(?=/)'), 'N'),                               # a numbered record in an address
    (re.compile(r'\b(id="m|href="#m|after=|before=)\d+'), r'\1N'),      # a message's number
    (re.compile(r'("key": ")\d+"'), r'\1N"'),                            # a numbered record's row key
    (re.compile(r'(\d\d:\d\d:\d\d)\.\d+'), r'\1'),                      # the world's clock's microseconds
)
# a record's id, with or without its dashes (a stored file is named by one)
_UUID = re.compile(r'[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}')


def normalised(text):
    """`text` with what varies put in a fixed form: each record id the n-th one it names, in order of appearance; a list of
    ids in one value (a select's `data-group`: a set, in no order) in their order."""
    for pattern, replacement in _VARIES:
        text = pattern.sub(replacement, text)
    seen = {}
    text = _UUID.sub(lambda match: seen.setdefault(match.group(0), f'<id {len(seen) + 1}>'), text)
    return _IDS.sub(lambda match: ' '.join(sorted(re.findall(r'<id \d+>', match.group(0)),
                                                  key=lambda each: int(each[4:-1]))), text)


_IDS = re.compile(r'<id \d+>(?: <id \d+>)+')


def _lines(path, text):
    """A fixture's lines to compare: JSON written on one line (the form oracle) is laid out a value a line first."""
    if path.endswith('.json') and '\n' not in text.strip():
        text = json.dumps(json.loads(text), ensure_ascii=False, indent=1)
    return text.splitlines()


def first_difference(path, recorded, rendered):
    """None when the two say the same once normalised; else where they part: the fixture's path, the line's number, the
    recorded line and the rendered one."""
    old, new = _lines(path, normalised(recorded)), _lines(path, normalised(rendered))
    if old == new:
        return None
    at = next(index for index in range(max(len(old), len(new)))
              if index >= len(old) or index >= len(new) or old[index] != new[index])
    said = lambda lines: repr(lines[at]) if at < len(lines) else '(nothing)'     # noqa: E731
    return f'{path}, line {at + 1}: recorded {said(old)}, rendered now {said(new)}'
