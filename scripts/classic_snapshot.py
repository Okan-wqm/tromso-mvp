"""Renders the CLASSIC pages of every form with a template of its own (new, editing each record of the test world, each
row list sent back refused) into a folder, one file a page, the per-request values blanked (CSRF tokens, entry keys):
run before and after a change to those templates and compare the folders (`diff -r`): the classic look must not change.
Run it as scripts/record_test_world.py runs (SCRIPT=scripts/classic_snapshot.py scripts/record_test_world.sh /app/.build/FOLDER), in the throwaway database
test_world: `python scripts/classic_snapshot.py <folder>`. Nothing is kept: one transaction, rolled back."""
import os
import re
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
    sys.exit('refused: only the throwaway database test_world')

from django.contrib.auth import get_user_model  # noqa: E402
from django.test import Client  # noqa: E402
from django.urls import reverse  # noqa: E402
from django.utils import translation  # noqa: E402

import_module(settings.ROOT_URLCONF)
from core.crud import Resource  # noqa: E402
from core.test_world import MOMENT, refused_rows_data, world  # noqa: E402

OUT = sys.argv[1]
BLANK = [(re.compile(r'(name="csrfmiddlewaretoken" value=")[^"]*'), r'\1-'),
         (re.compile(r'(name="entry_key" value=")[^"]*'), r'\1-'),
         (re.compile(r'(id="[^"]*?)[0-9a-f]{32}'), r'\1-'),
         (re.compile(r'nonce="[^"]*"'), 'nonce="-"'),
         (re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'), 'UUID'),
         (re.compile(r'(name="seed" value=")[0-9]*'), r'\1-'),     # a random seed offered each time
         (re.compile(r'\?v=\d+'), '?v=-'),                          # a static file's version (its build time)
         (re.compile(r'\b[0-9a-f]{64}\b'), 'HASH')]                  # a report's content hash (over its records' keys)


class Rollback(Exception):
    pass


def ported():
    return [resource for resource in Resource.registry if resource.form_class is not None
            and resource.form_template != 'crud/form.html']


try:
    with transaction.atomic(), mock.patch('django.utils.timezone.now', return_value=MOMENT), translation.override('en'):
        admin = get_user_model().objects.create_superuser('test.admin', 'test.admin@example.com', 'x')
        world(admin)
        client = Client(HTTP_HOST='localhost')
        client.force_login(admin)
        os.makedirs(OUT, exist_ok=True)
        count = 0
        for language in ('en', 'nb', 'tr'):
            client.cookies['django_language'] = language
            for resource in ported():
                pages = [('new', 'get', reverse(resource.url_name('create')), None)] if resource.allows('add') else []
                if resource.allows('change'):
                    # in an order two runs share (keys are random)
                    for index, record in enumerate(sorted(resource.queryset(), key=str)[:5]):
                        pages.append((f'edit-{index}', 'get', reverse(resource.url_name('edit'), args=[record.pk]), None))
                        for rows in resource.row_lists:
                            if rows.applies_to(record):
                                pages.append((f'edit-{index}-{rows.key}-refused', 'post',
                                              f"{reverse(resource.url_name(rows.key), args=[record.pk])}?ui=classic",
                                              refused_rows_data(rows, record)))
                        # the read pages that include the same partials (a design's table, an entry's review)
                        if resource.detail_template:
                            pages += [(f'detail-{index}-{tab}', 'get', f"{reverse(resource.url_name('detail'), args=[record.pk])}"
                                       f"{'?tab=' + tab if tab else ''}", None)
                                      for tab in ('', 'data', 'team')]
                for what, method, url, data in pages:
                    answer = client.get(url, {'ui': 'classic'}) if method == 'get' else client.post(url, data)
                    html = answer.content.decode()
                    for pattern, blank in BLANK:
                        html = pattern.sub(blank, html)
                    with open(f'{OUT}/{language}-{resource.__name__}-{what}.html', 'w', encoding='utf-8') as out:
                        out.write(f'{answer.status_code}\n{html}')
                    count += 1
        print(f'{count} classic pages written to {OUT}')
        raise Rollback
except Rollback:
    pass
