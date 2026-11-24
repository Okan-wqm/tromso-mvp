"""Records the browser tests' fixtures from the TEST WORLD, never from the development database:
    frontend/test/pages/form-oracle.json      every visible field of every tab's form (new, sent empty, editing a record
                                               of the test world, the rows of its row lists), with the controls the
                                               server's own field template draws for it (core/tests_formpayload.py's
                                               reading), and the handling acknowledgement;
    frontend/test/pages/company-props-<language>.json   Company › Overview's props (config/company_props.py) in en, nb, tr;
    frontend/test/pages/list-props-<language>.json      the list pages' props (core/listprops.py) in en, nb, tr;
    frontend/test/pages/panel-props-<language>.json     the same of the production panel's list pages;
    frontend/test/pages/panel/<page>-<language>.html    the production panel's pages drawn by the server (Tasks with its
                                               drawer, Regulatory reports, Storage, Messages), whole, in the new look.

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
from core.test_world import MOMENT, world  # noqa: E402

OUT = '/app/frontend/test/pages'


class Rollback(Exception):
    pass


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
        record = resource.queryset().order_by('pk').first() if resource.allows('change') else None
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


def record_panel_pages(admin):
    """Writes the server's answer of every page of panel_pages() in the new look, in en, nb and tr: a session's token
    replaced by a fixed word, nothing else changed."""
    import re
    from django.test import Client
    client = Client(HTTP_HOST='localhost')
    client.force_login(admin)
    client.cookies['ui'] = 'next'
    os.makedirs(f'{OUT}/panel', exist_ok=True)
    for language in ('en', 'nb', 'tr'):
        client.cookies['django_language'] = language
        for name, address in panel_pages().items():
            html = client.get(address).content.decode()
            html = re.sub(r'(name="csrfmiddlewaretoken" value=")[^"]+', lambda found: found.group(1) + 'test-token', html)
            with open(f'{OUT}/panel/{name}-{language}.html', 'w', encoding='utf-8') as out:
                out.write(html)


def record_lists(admin, lists=LISTS):
    """{language: {name: the list-page island's props}} of every list in `lists`, as the test world's admin sees it."""
    import re
    from django.test import Client
    from django.urls import reverse
    client = Client(HTTP_HOST='localhost')
    client.force_login(admin)
    found = {}
    for language in ('en', 'nb', 'tr'):
        client.cookies['django_language'] = language
        pages = {}
        for name, route in lists.items():
            url, _sep, query = route.partition('?')
            html = client.get(f'{reverse(url)}?{query}&ui=next' if query else f'{reverse(url)}?ui=next').content.decode()
            block = re.search(r'<script id="island-list-page-1" type="application/json">(.*?)</script>', html, re.S)
            if block is None:
                sys.exit(f'refused: {route} has no list-page island')
            pages[name] = json.loads(block.group(1))
            pages[name]['csrfToken'] = 'test-token'          # a session's token is no fixture
        found[language] = pages
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
        for language, pages in record_lists(admin, PANEL_LISTS).items():
            with open(f'{OUT}/panel-props-{language}.json', 'w', encoding='utf-8') as out:
                json.dump(pages, out, ensure_ascii=False, indent=1)
                out.write(chr(10))
        record_panel_pages(admin)
        raise Rollback
except Rollback:
    pass
print('made:', '; '.join(made))
print(f'{len(unique)} distinct fields; no record to edit for: {", ".join(missing)}')
