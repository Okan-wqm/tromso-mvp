"""Records the browser tests' fixtures from the TEST WORLD, never from the development database:
    frontend/test/pages/form-oracle.json      every visible field of every tab's form (new, sent empty, editing a record
                                               of the test world, the rows of its row lists), with the controls the
                                               server's own field template draws for it (core/tests_formpayload.py's
                                               reading), and the handling acknowledgement;
    frontend/test/pages/company-props-<language>.json   Company › Overview's props (config/company_props.py) in en, nb, tr.

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
        raise Rollback
except Rollback:
    pass
print('made:', '; '.join(made))
print(f'{len(unique)} distinct fields; no record to edit for: {", ".join(missing)}')
