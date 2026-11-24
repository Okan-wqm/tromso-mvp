"""Records the browser tests' fixtures from the TEST WORLD, never from the development database:
    frontend/test/pages/form-oracle.json      every visible field of every tab's form (new, sent empty, editing a record
                                               of the test world, the rows of its row lists, a row list sent back
                                               refused), with the controls the server's own field template draws for it
                                               (core/tests_formpayload.py's reading), and the handling acknowledgement;
    frontend/test/pages/company-props-<language>.json   Company › Overview's props (config/company_props.py) in en, nb, tr;
    frontend/test/pages/list-props-<language>.json      the list pages' props (core/listprops.py) in en, nb, tr;
    frontend/test/pages/form-props-<language>.json      the record-form island's props of every form with a template of its
                                                        own that the island draws (core/formpanels.py), new and editing,
                                                        in en, nb, tr.

Every person, address and name in them is a fixture value (names "Test …", addresses @example.com); the guard
core/tests_fixture_privacy.py fails on any other e-mail domain under frontend/test and core/testdata.

Run it in the test runner's image against a THROWAWAY database (scripts/record_test_world.sh starts one, migrates it, runs
this and removes it); it refuses any database not named `test_world`. Everything is made in one transaction that is
rolled back. With the clock pinned, two runs give the same fields; record ids differ."""
import json
import os
import sys
from importlib import import_module
from unittest import mock

sys.path.insert(0, '/app')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django  # noqa: E402

django.setup()
from django.conf import settings  # noqa: E402
from django.db import connection, transaction  # noqa: E402

if connection.settings_dict['NAME'] != 'test_world':
    sys.exit('refused: this records fixtures only from the throwaway database test_world (scripts/record_test_world.sh)')

from django import forms  # noqa: E402
from django.contrib.auth import get_user_model  # noqa: E402
from django.test import RequestFactory  # noqa: E402
from django.utils import translation  # noqa: E402

import_module(settings.ROOT_URLCONF)
from core.crud import Resource  # noqa: E402
from core.formpayload import UnknownWidget, field_payload, unshown_visible_fields  # noqa: E402
from core.formprops import DRAWN  # noqa: E402
from core.tests_formpayload import drawn  # noqa: E402
from core.test_world import MOMENT, record_of, refused_rows_data, world  # noqa: E402

OUT = '/app/frontend/test/pages'


class Rollback(Exception):
    pass


def refused_rows(rows, record):
    """A row list of `record` sent back refused (core.test_world.refused_rows_data), checked, so each field carries the
    value sent and the server's errors."""
    sent = rows.formset(refused_rows_data(rows, record), instance=record, prefix=rows.key)
    sent.is_valid()
    return sent


def cases_of(admin):
    """[{case, field, controls}] of every tab's forms in the test world."""
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
        record = record_of(resource) if resource.allows('change') else None
        if record is None:
            missing.append(resource.__name__)
            continue
        cases += fields(f'{resource.__name__} edit', resource.form(request(), instance=record))
        for key, formset in resource.edit_extras(request(), record).items():
            if isinstance(formset, forms.BaseFormSet):
                for index, row in enumerate([*formset.forms, formset.empty_form]):
                    cases += fields(f'{resource.__name__} rows {key} {index}', row)
        for rows in resource.row_lists:
            if rows.applies_to(record):
                cases += [case for row in refused_rows(rows, record).forms
                          for case in fields(f'{resource.__name__} rows {rows.key} refused', row)]
    from farm.forms.stock import handling_ack_field

    class Acknowledged(forms.Form):
        go_on = handling_ack_field('harvest')
    acknowledged = Acknowledged()
    acknowledged.fields['go_on'].widget.fingerprint = 'f00d'
    cases += fields('handling acknowledgement', acknowledged)
    return cases, missing


# The list pages drawn by the list-page island (core/listprops.py) whose props are recorded: {name: address}.
LISTS = {
    'team': 'hr:employee_list', 'team-production': 'hr:production_employee_list',
    'departments': 'hr:officedepartment_list', 'attendance': 'hr:attendancerecord_list',
    'leave': 'hr:leaverequest_list', 'leave-all': 'hr:leaverequest_list?tab=all', 'shifts': 'hr:shift_list',
    'holidays': 'hr:holiday_list', 'leave-types': 'hr:leavetype_list',
}


def record_lists(admin):
    """{language: {name: the list-page island's props}} of every list in LISTS, as the test world's admin sees it."""
    import re
    from django.test import Client
    from django.urls import reverse
    client = Client(HTTP_HOST='localhost')
    client.force_login(admin)
    found = {}
    for language in ('en', 'nb', 'tr'):
        client.cookies['django_language'] = language
        pages = {}
        for name, route in LISTS.items():
            url, _sep, query = route.partition('?')
            html = client.get(f'{reverse(url)}?{query}&ui=next' if query else f'{reverse(url)}?ui=next').content.decode()
            block = re.search(r'<script id="island-list-page-1" type="application/json">(.*?)</script>', html, re.S)
            if block is None:
                sys.exit(f'refused: {route} has no list-page island')
            pages[name] = json.loads(block.group(1))
            pages[name]['csrfToken'] = 'test-token'          # a session's token is no fixture
        found[language] = pages
    return found


def record_forms(admin):
    """{language: {'<tab> new' | '<tab> edit': the record-form island's props}} of every form with a template of its own
    that the island draws (its Resource words the template's panels: core/formpanels.py), as the test world's admin sees
    it, editing every record of the tab in the test world (up to five)."""
    import re
    from django.test import Client
    from django.urls import reverse
    client = Client(HTTP_HOST='localhost')
    client.force_login(admin)
    ported = [resource for resource in Resource.registry if resource.form_class is not None
              and resource.form_template != 'crud/form.html'
              and resource.next_panels.__func__ is not Resource.next_panels.__func__]
    found = {}
    for language in ('en', 'nb', 'tr'):
        client.cookies['django_language'] = language
        pages = {}
        for resource in ported:
            urls = {'new': reverse(resource.url_name('create'))} if resource.allows('add') else {}
            # every record of the test world (up to five, as the page walk of core/tests_formpanels.py): a draft and a
            # fixed feeding protocol, a draft and a started experiment, a lice and a biomass report
            if resource.allows('change'):
                for index, record in enumerate(resource.queryset().order_by('pk')[:5]):
                    urls[f'edit {index}'] = reverse(resource.url_name('edit'), args=[record.pk])
            for what, url in urls.items():
                html = client.get(f'{url}?ui=next').content.decode()
                block = re.search(r'<script id="island-record-form-1" type="application/json">(.*?)</script>', html, re.S)
                if block is None:
                    sys.exit(f'refused: {url} has no record-form island')
                pages[f'{resource.__name__} {what}'] = {**json.loads(block.group(1)), 'csrfToken': 'test-token'}
        pages.update(refused_with_question(client))
        found[language] = pages
    return found


class Asked:
    """A change the withdrawal guard asks about, as farm.health.withdrawal.Change gives it to the page (a fixture's
    warning; the fingerprint a fixture value)."""

    def __init__(self, second_person=''):
        self.fingerprint, self.second_person = 'f00dfeed', second_person

    def messages(self):
        return ['Test harvest of 21.11.2026 lies inside this withdrawal (end unknown).']


def refused_with_question(client):
    """{'FeedResource refused' | 'FeedResource refused, second person': props} of the test world's feed saved again and
    refused by the withdrawal guard (review B4: the question box in the browser tests' axe and CSP run): the edit goes
    through the one edit view with what its form holds, the guard's answer stood in for (core/tests_formpanels.py holds
    the real guard: a feed made medicated over a recorded harvest), with the box, and with a second person's approval and
    no box."""
    import re
    from django.core.exceptions import ValidationError
    from django.urls import reverse
    from farm.models import Feed
    from farm.resources.feed import FeedResource
    feed = Feed.objects.get(code='TFE')
    url = reverse(FeedResource.url_name('edit'), args=[feed.pk])
    form = FeedResource.form(None, instance=feed)
    data = {}
    for bound in form:
        value = bound.value()
        if isinstance(value, (list, tuple)):
            data[bound.html_name] = [str(each) for each in value]
        elif isinstance(value, bool):
            if value:
                data[bound.html_name] = 'on'
        elif value is not None:
            data[bound.html_name] = str(value)
    found = {}
    for name, second in (('FeedResource refused', ''),
                         ('FeedResource refused, second person', 'A second person must approve this change.')):
        def refuse(cls, request, read, write, seen, second=second):
            error = ValidationError(['Tick the box to go on despite these warnings.'])
            error.change = Asked(second)
            raise error
        with mock.patch.object(FeedResource, 'edited', classmethod(refuse)):
            html = client.post(f'{url}?ui=next', data).content.decode()
        block = re.search(r'<script id="island-record-form-1" type="application/json">(.*?)</script>', html, re.S)
        if block is None or '"question": {' not in block.group(1):
            sys.exit(f'refused: the refused feed has no question box ({name})')
        found[name] = {**json.loads(block.group(1)), 'csrfToken': 'test-token'}
    return found


try:
    with transaction.atomic(), mock.patch('django.utils.timezone.now', return_value=MOMENT), translation.override('en'):
        admin = get_user_model().objects.create_superuser('test.admin', 'test.admin@example.com', 'x')
        made = world(admin)
        cases, missing = cases_of(admin)
        seen, unique = set(), []
        for case in cases:
            key = json.dumps([case['field'], case['controls']], sort_keys=True)
            if key not in seen:
                seen.add(key)
                unique.append(case)
        with open(f'{OUT}/form-oracle.json', 'w', encoding='utf-8') as out:
            json.dump({'cases': unique}, out, ensure_ascii=False)
        from config.company_props import overview_props
        for language in ('en', 'nb', 'tr'):
            with translation.override(language):
                with open(f'{OUT}/company-props-{language}.json', 'w', encoding='utf-8') as out:
                    json.dump(overview_props(admin, MOMENT), out, ensure_ascii=False, indent=1)
                    out.write('\n')
        for language, pages in record_lists(admin).items():
            with open(f'{OUT}/list-props-{language}.json', 'w', encoding='utf-8') as out:
                json.dump(pages, out, ensure_ascii=False, indent=1)
                out.write(chr(10))
        for language, pages in record_forms(admin).items():
            with open(f'{OUT}/form-props-{language}.json', 'w', encoding='utf-8') as out:
                json.dump(pages, out, ensure_ascii=False, indent=1)
                out.write(chr(10))
        raise Rollback
except Rollback:
    pass
print('made:', '; '.join(made))
print(f'{len(unique)} distinct fields; no record to edit for: {", ".join(missing)}')
