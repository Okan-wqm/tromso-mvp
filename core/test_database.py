import csv
import io
import re
import uuid
from unittest import mock

from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse

from farm.models import ProductionDepartment, Site, SiteContact, Tank

from . import access, database, dbgrid
from .database import Section, Viewer
from .models import AuditLog

User = get_user_model()

# A viewer that hides one table and masks one column, for the tests that change the configuration.
HIDING_SITES = Viewer(sections=[Section('Facility', ('farm',))], excluded=('sites',))
MASKING_DESCRIPTION = Viewer(sections=[Section('Facility', ('farm',))], masked={'sites': ('description',)})


def table_url(name):
    return reverse('core:database_table', args=[name])


def export_url(name):
    return reverse('core:database_export', args=[name])


def column(response, name):
    """What the grid shows in the column `name`, row by row."""
    grid = response.context['grid']
    index = [c.name for c in grid.columns].index(name)
    return [row.cells[index].text for row in grid.rows]


def csv_rows(response):
    """The CSV a response carries, header first."""
    assert response.streaming, 'the export must be streamed'
    return list(csv.reader(io.StringIO(b''.join(response.streaming_content).decode('utf-8-sig'))))


def exported(response):
    """The CSV's rows as dicts under the header."""
    header, *rows = csv_rows(response)
    return [dict(zip(header, row)) for row in rows]


def names():
    return [table.name for _, tables in database.sections() for table in tables]


class DatabaseViewerTestCase(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('root', 'root@example.com', 'hemmelig-123')
        self.client.force_login(self.admin)

    def make_site(self, **fields):
        fields.setdefault('name', 'Bergen Hatchery')
        fields.setdefault('code', 'BH')
        return Site.objects.create(**fields)

    def page(self, name, **query):
        return self.client.get(table_url(name), query)

    def download(self, name, **query):
        return self.client.get(export_url(name), query)


class AccessTests(DatabaseViewerTestCase):
    def test_the_platform_admin_sees_the_database(self):
        self.assertEqual(self.client.get(reverse('core:database')).status_code, 200)
        self.assertContains(self.client.get(reverse('home')), f'href="{reverse("core:database")}"')

    def test_everyone_else_is_refused_however_much_they_may_do_elsewhere(self):
        everything_else = User.objects.create_user('kari', 'kari@example.com', 'hemmelig-123')
        everything_else.user_permissions.set(Permission.objects.exclude(codename='browse_database'))
        self.client.force_login(everything_else)
        for url in (reverse('core:database'), table_url('sites'), export_url('sites')):
            self.assertEqual(self.client.get(url).status_code, 403, url)
        self.assertNotContains(self.client.get(reverse('home')), reverse('core:database'))

    def test_the_permission_is_real_and_not_for_roles(self):
        self.assertTrue(Permission.objects.filter(content_type__app_label='core', codename='browse_database').exists())
        self.assertNotIn('core.browse_database', {access.perm_name(p) for p in access.permissions()})
        granted = User.objects.create_user('kari', 'kari@example.com', 'hemmelig-123')
        granted.user_permissions.add(Permission.objects.get(codename='browse_database'))
        self.client.force_login(granted)
        self.assertEqual(self.client.get(reverse('core:database')).status_code, 200)

    def test_signing_in_is_required(self):
        self.client.logout()
        self.assertRedirects(self.client.get(reverse('core:database')),
                             f'{reverse("login")}?next={reverse("core:database")}')

    def test_it_is_read_only(self):
        self.make_site()
        for url in (reverse('core:database'), table_url('sites'), export_url('sites')):
            for method in ('post', 'put', 'patch', 'delete'):
                self.assertEqual(getattr(self.client, method)(url).status_code, 405, (method, url))
        self.assertEqual(Site.objects.count(), 1)
        self.assertEqual(self.client.head(table_url('sites')).status_code, 200)

    def test_only_the_tables_of_the_listed_apps_exist(self):
        for name in ('django_session', 'django_migrations', 'django_content_type', 'django_admin_log', 'nonsense'):
            self.assertEqual(self.page(name).status_code, 404, name)
            self.assertEqual(self.download(name).status_code, 404, name)


class RegistryTests(DatabaseViewerTestCase):
    def test_tables_come_from_the_models_of_the_listed_apps(self):
        expected = {model._meta.db_table for label in ('farm', 'messaging', 'core', 'auth')
                    for model in apps.get_app_config(label).get_models(include_auto_created=True)}
        self.assertEqual(set(names()), expected)
        self.assertTrue({'sites', 'site_contacts', 'production_departments', 'audit_log', 'auth_user',
                         'auth_group', 'auth_permission', 'auth_user_groups'} <= expected)
        self.assertNotIn('django_session', expected)

    def test_tables_are_grouped_in_sections(self):
        sections = dict(database.sections())
        facility = [t.name for t in sections['Facility']]
        self.assertEqual(facility, sorted(facility))
        self.assertTrue({'production_departments', 'site_contacts', 'sites'} <= set(facility))
        self.assertIn('audit_log', [t.name for t in sections['Administration']])
        self.assertIn('auth_user', [t.name for t in sections['Administration']])

    def test_descriptions_come_from_the_model_or_the_configuration(self):
        found = {table.name: table.description for _, tables in database.sections() for table in tables}
        self.assertEqual(found['sites'], 'A physical facility (locality).')
        self.assertEqual(found['audit_log'], 'Who did what to which record, with old and new values.')
        self.assertEqual(found['auth_user_groups'], 'Which roles each user has.')
        self.assertTrue(all(description for description in found.values()))

    @override_settings(DATABASE_VIEWER='core.test_database.HIDING_SITES')
    def test_the_configuration_decides_what_is_shown(self):
        self.assertNotIn('sites', names())
        self.assertNotIn('auth_user', names())
        self.assertEqual(self.page('sites').status_code, 404)
        self.assertEqual(self.page('production_departments').status_code, 200)

    def test_every_table_matches_its_model(self):
        for _, tables in database.sections():
            for table in tables:
                with self.subTest(table=table.name):
                    columns = table.structure().columns
                    self.assertTrue(all(c.field is not None for c in columns), 'a column the model does not have')
                    self.assertEqual({c.name for c in columns},
                                     {f.column for f in table.model._meta.concrete_fields})

    def test_masked_columns_exist_and_every_secret_looking_column_is_masked(self):
        config = database.viewer()
        for name, columns in config.masked.items():
            self.assertIn(name, names())
            self.assertTrue(set(columns) <= {c.name for c in database.find(name).structure().columns}, name)
        for _, tables in database.sections():
            for table in tables:
                for c in table.structure().columns:
                    if re.search(r'password|secret|token|session', c.name):
                        self.assertTrue(c.masked, f'{table.name}.{c.name} looks secret and is not masked')


class OverviewTests(DatabaseViewerTestCase):
    def test_every_table_is_listed_with_its_name_and_a_link(self):
        response = self.client.get(reverse('core:database'))
        for name in names():
            self.assertContains(response, f'href="{table_url(name)}"')
            self.assertContains(response, f'>{name}</a>')
        self.assertContains(response, 'A physical facility (locality).')

    def test_rows_and_deleted_rows_are_counted(self):
        live = self.make_site()
        gone = self.make_site(name='Tromsø', code='TS')
        gone.soft_delete(self.admin)
        ProductionDepartment.objects.create(name='Hall', code='H', site=live)
        entries = {entry['table'].name: entry for section in self.client.get(reverse('core:database')).context['sections']
                   for entry in section['tables']}
        self.assertEqual((entries['sites']['rows'], entries['sites']['deleted']), (2, 1))
        halls = entries['production_departments']
        self.assertEqual((halls['rows'], halls['deleted']), (1, 0))
        self.assertEqual(entries['auth_user']['rows'], 1)
        self.assertEqual(entries['audit_log']['rows'], AuditLog.objects.count())
        self.assertIsNone(entries['audit_log']['deleted'])   # this table does not soft-delete


class EveryTableTests(DatabaseViewerTestCase):
    """Loops over the registry, so a table that is added later is covered without a new test."""

    def setUp(self):
        super().setUp()
        site = self.make_site(facilities={'tanks': 3}, notes='x' * 300)
        SiteContact.objects.create(site=site, name='Kari', is_primary=True)
        hall = ProductionDepartment.objects.create(name='Hall', code='H', site=site, manager=self.admin)
        # A table with generated columns (the volumes the database works out).
        Tank.objects.create(name='Tank', code='T', kind='tank', production_department=hall, water_type='freshwater',
                            shape='circular', material='concrete', diameter=2, depth=1, max_density_kg_m3=50)
        AuditLog.objects.create(user=self.admin, user_name='root', action='create', entity_type='site',
                                entity_id=str(site.pk), entity_label='Bergen Hatchery (BH)', changes={'Name': [None, 'x']})

    def test_data_and_structure_render_and_the_export_matches_the_columns(self):
        for name in names():
            with self.subTest(table=name):
                response = self.page(name)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'data-panel="data"')
                self.assertContains(response, 'data-panel="structure"')
                readable = [c.name for c in response.context['grid'].readable]
                download = self.download(name)
                self.assertEqual(download.status_code, 200)
                self.assertEqual(csv_rows(download)[0], readable)

    def test_every_column_of_every_table_can_be_sorted_searched_and_filtered(self):
        probes = ['x', '1', 'true', str(uuid.uuid4()), '99999999999999999999', 'NaN', '1e999', '%', '\0']
        for name in names():
            table = database.find(name)
            structure = table.structure()
            columns = [c.name for c in structure.columns if not c.masked]
            with self.subTest(table=name):
                self.assertEqual(self.page(name, sort=columns[0], dir='desc').status_code, 200)
                for query in [{'sort': c} for c in columns] + [{'q': p} for p in probes] + [{f'f_{c}': p for c in columns} for p in probes]:
                    grid = dbgrid.Grid(table, structure, query)
                    self.assertIsInstance(grid.rows, list)   # runs the query and builds every cell
                    if 'sort' not in query:
                        list(grid.export())


class GridTests(DatabaseViewerTestCase):
    def setUp(self):
        super().setUp()
        self.bergen = self.make_site(latitude='60.391300', longitude='5.322100')
        self.tromso = self.make_site(name='Tromsø Grow-out', code='TG')
        self.alta = self.make_site(name='Alta Smolt', code='AS', lokalitetsnummer=12345)

    def names(self, **query):
        return column(self.page('sites', **query), 'name')

    def test_rows_are_shown_in_the_models_own_order_and_numbered(self):
        response = self.page('sites')
        self.assertEqual(column(response, 'name'), ['Alta Smolt', 'Bergen Hatchery', 'Tromsø Grow-out'])
        self.assertEqual([row.number for row in response.context['grid'].rows], [1, 2, 3])
        self.assertContains(response, 'Rows 1–3 of 3')

    def test_a_column_header_sorts_both_ways(self):
        self.assertEqual(self.names(sort='code'), ['Alta Smolt', 'Bergen Hatchery', 'Tromsø Grow-out'])
        self.assertEqual(self.names(sort='code', dir='desc'), ['Tromsø Grow-out', 'Bergen Hatchery', 'Alta Smolt'])
        header = {h.column.name: h for h in self.page('sites', sort='code').context['grid'].headers}
        self.assertEqual(header['code'].direction, 'ascending')
        self.assertIn('dir=desc', header['code'].sort_href)   # a second click reverses it
        self.assertEqual(header['name'].direction, '')

    def test_empty_values_sort_last_in_both_directions(self):
        self.assertEqual(self.names(sort='lokalitetsnummer')[0], 'Alta Smolt')
        self.assertEqual(self.names(sort='lokalitetsnummer', dir='desc')[0], 'Alta Smolt')

    def test_anything_that_is_not_a_column_is_ignored(self):
        plain = self.names()
        for query in ({'sort': 'nonsense'}, {'sort': 'name;DROP TABLE sites'}, {'sort': '-name'}, {'dir': 'sideways'},
                      {'f_nonsense': 'x'}, {'f_': 'x'}, {'deleted': 'maybe'}, {'sort': 'pk'}):
            self.assertEqual(self.names(**query), plain, query)
        self.assertEqual(Site.objects.count(), 3)

    def test_a_filter_under_a_column_matches_text_inside_and_numbers_whole(self):
        self.assertEqual(self.names(f_name='ber'), ['Bergen Hatchery'])
        self.assertEqual(self.names(f_name='GROW'), ['Tromsø Grow-out'])
        self.assertEqual(self.names(f_lokalitetsnummer='12345'), ['Alta Smolt'])
        self.assertEqual(self.names(f_lokalitetsnummer='1234'), [])
        self.assertEqual(self.names(f_latitude='60.391300'), ['Bergen Hatchery'])
        self.assertEqual(self.names(f_id=self.tromso.pk), ['Tromsø Grow-out'])
        self.assertEqual(self.names(f_is_active='true'), ['Alta Smolt', 'Bergen Hatchery', 'Tromsø Grow-out'])
        self.assertEqual(self.names(f_is_active='false'), [])
        self.assertEqual(self.names(f_name='o', f_code='tg'), ['Tromsø Grow-out'])

    def test_a_filter_that_cannot_match_the_column_type_matches_nothing(self):
        for query in ({'f_lokalitetsnummer': 'abc'}, {'f_id': 'not-a-uuid'}, {'f_latitude': 'NaN'},
                      {'f_version': '99999999999999999999'}, {'f_is_active': 'maybe'}):
            self.assertEqual(self.names(**query), [], query)

    def test_wildcard_characters_are_plain_text(self):
        self.assertEqual(self.names(f_name='%'), [])
        self.assertEqual(self.names(q='b_s'), [])        # no wildcard: "land_based" has "bas" but not "b_s"
        self.assertEqual(self.names(f_name='b_rgen'), [])

    def test_the_search_box_looks_in_every_column(self):
        self.assertEqual(self.names(q='bergen'), ['Bergen Hatchery'])
        self.assertEqual(self.names(q='tg'), ['Tromsø Grow-out'])   # a code
        self.assertEqual(self.names(q='SMOLT'), ['Alta Smolt'])     # text inside a name
        self.assertEqual(self.names(q='12345'), ['Alta Smolt'])
        self.assertEqual(self.names(q=self.alta.pk), ['Alta Smolt'])
        self.assertEqual(self.names(q='nothing like it'), [])
        self.assertEqual(self.names(q='  bergen  ', f_code='bh'), ['Bergen Hatchery'])

    def test_a_hundred_rows_make_a_page(self):
        Site.objects.bulk_create([Site(name=f'Site {i:03}', code=f'S{i:03}') for i in range(202)])   # 205 in all
        grid = lambda **query: self.page('sites', **query).context['grid']
        first = grid()
        self.assertEqual((len(first.rows), first.page.paginator.count, first.page.paginator.num_pages), (100, 205, 3))
        self.assertEqual((first.rows[0].number, first.rows[-1].number), (1, 100))
        self.assertEqual(grid(page=2).rows[0].number, 101)
        last = grid(page=3)
        self.assertEqual((len(last.rows), last.rows[0].number, last.rows[-1].number), (5, 201, 205))
        for page in ('0', '-4', 'abc', ''):
            self.assertEqual(grid(page=page).page.number, 1, page)
        self.assertEqual(grid(page=99).page.number, 3)
        self.assertContains(self.page('sites', page=2), 'Rows 101–200 of 205')
        # Moving between pages keeps the sort and the filters; changing them starts again on page 1.
        pager = grid(sort='code', dir='desc', f_name='site').pager
        self.assertIn('sort=code', pager['next'])
        self.assertIn('f_name=site', pager['next'])
        self.assertIn('page=2', pager['next'])
        self.assertEqual(pager['previous'], '')

    def test_the_numbers_of_pages_are_for_the_filtered_rows(self):
        response = self.page('sites', f_name='alta')
        self.assertContains(response, 'Rows 1–1 of 1 match')
        self.assertContains(self.page('sites', f_name='zzz'), 'No rows match')


class DeletedRowsTests(DatabaseViewerTestCase):
    def setUp(self):
        super().setUp()
        self.live = self.make_site()
        self.gone = self.make_site(name='Tromsø Grow-out', code='TG')
        self.gone.soft_delete(self.admin)

    def names(self, **query):
        return column(self.page('sites', **query), 'name')

    def test_deleted_rows_are_shown_and_marked(self):
        response = self.page('sites')
        self.assertEqual(self.names(), ['Bergen Hatchery', 'Tromsø Grow-out'])
        self.assertEqual([row.deleted for row in response.context['grid'].rows], [False, True])
        self.assertContains(response, 'class="grid-deleted"', count=1)
        self.assertContains(response, 'title="Deleted row"', count=1)

    def test_deleted_rows_can_be_hidden_or_shown_alone(self):
        self.assertEqual(self.names(deleted='show'), ['Bergen Hatchery', 'Tromsø Grow-out'])
        self.assertEqual(self.names(deleted='hide'), ['Bergen Hatchery'])
        self.assertEqual(self.names(deleted='only'), ['Tromsø Grow-out'])
        self.assertEqual(self.names(deleted='only', f_name='bergen'), [])
        self.assertContains(self.page('sites', deleted='only'), 'Rows 1–1 of 1 match')
        self.assertEqual([row['name'] for row in exported(self.download('sites', deleted='hide'))],
                         ['Bergen Hatchery'])

    def test_the_choice_is_offered_only_where_rows_can_be_deleted(self):
        self.assertContains(self.page('sites'), 'id="grid-deleted"')
        response = self.page('audit_log', deleted='only')
        self.assertNotContains(response, 'id="grid-deleted"')
        self.assertEqual(response.context['grid'].deleted, 'show')


class ValuesTests(DatabaseViewerTestCase):
    def cells(self, table, **query):
        grid = self.page(table, **query).context['grid']
        return {c.name: cell for c, cell in zip(grid.columns, grid.rows[0].cells)}

    def test_values_are_shown_as_stored(self):
        site = self.make_site(latitude='60.391300', longitude='5.322100', altitude='-5.50', facilities={'name': 'ø', 'tanks': 3},
                              established_date='2020-01-02')
        cells = self.cells('sites')
        self.assertEqual(cells['latitude'].text, '60.391300')           # not rounded or localised
        self.assertEqual(cells['latitude'].kind, 'number')
        self.assertEqual(cells['altitude'].text, '-5.50')
        self.assertEqual(cells['version'].text, '1')
        self.assertEqual(cells['established_date'].text, '2020-01-02')
        self.assertEqual(cells['facilities'].text, '{"name": "ø", "tanks": 3}')
        self.assertEqual(cells['lokalitetsnummer'].kind, 'null')
        self.assertEqual(cells['is_deleted'].kind, 'bool')
        self.assertEqual(cells['is_deleted'].text, 'false')
        self.assertEqual(cells['id'].kind, 'uuid')
        self.assertEqual((cells['id'].text, cells['id'].full), (f'{str(site.pk)[:8]}…', str(site.pk)))
        # Timestamps as PostgreSQL prints them: the text a filter matches.
        with connection.cursor() as cursor:
            cursor.execute('SELECT created_at::text FROM sites')
            self.assertEqual(cells['created_at'].text, cursor.fetchone()[0])

    def test_the_html_marks_each_kind_of_value(self):
        site = self.make_site(notes='n' * 200, facilities={'a': 1})
        html = self.page('sites').content.decode()
        self.assertIn(f'title="{site.pk}">{str(site.pk)[:8]}…', html)
        self.assertIn('<span class="null">NULL</span>', html)
        self.assertIn('class="bool-false"', html)
        self.assertIn('<details class="more"><summary>' + 'n' * 80 + '…</summary><pre>' + 'n' * 200 + '</pre>', html)
        self.assertIn('{&quot;a&quot;: 1}', html)

    def test_long_json_opens_pretty_printed(self):
        self.make_site(facilities={'floor': ['a' * 50, 'b' * 50]})
        cell = self.cells('sites')['facilities']
        self.assertEqual(cell.kind, 'long')
        self.assertIn('\n  "floor": [\n', cell.full)

    def test_a_link_shows_the_stored_id_and_the_record_it_points_at(self):
        site = self.make_site()
        ProductionDepartment.objects.create(name='Hall', code='H', site=site, created_by=self.admin)
        cells = self.cells('production_departments')
        link = cells['site_id']
        self.assertEqual((link.kind, link.text, link.full, link.label), ('fk', f'{str(site.pk)[:8]}…', str(site.pk), 'Bergen Hatchery (BH)'))
        self.assertEqual(link.href, f'{reverse("core:database_table", args=["sites"])}?f_id={site.pk}')
        self.assertEqual((cells['created_by_id'].text, cells['created_by_id'].label), (str(self.admin.pk), 'root'))
        self.assertEqual(cells['created_by_id'].href, f'{reverse("core:database_table", args=["auth_user"])}?f_id={self.admin.pk}')
        self.assertEqual(cells['manager_id'].kind, 'null')
        # The link leads to that one row.
        followed = self.client.get(link.href)
        self.assertEqual(column(followed, 'name'), ['Bergen Hatchery'])

    def test_a_link_to_a_row_that_is_gone_says_so(self):
        user = User.objects.create_user('kari', 'kari@example.com', 'hemmelig-123')
        AuditLog.objects.create(user=user, user_name='kari', action='create', entity_type='site', entity_id='1', entity_label='x')
        user.delete()
        cell = self.cells('audit_log')['user_id']
        self.assertEqual((cell.kind, cell.label), ('fk', None))
        self.assertContains(self.page('audit_log'), 'no such row')

    def test_a_link_to_a_deleted_record_still_shows_it(self):
        site = self.make_site()
        ProductionDepartment.objects.create(name='Hall', code='H', site=site)
        site.soft_delete(self.admin)
        self.assertEqual(self.cells('production_departments')['site_id'].label, 'Bergen Hatchery (BH)')


class MaskingTests(DatabaseViewerTestCase):
    def setUp(self):
        super().setUp()
        self.person = User.objects.create_user('kari', 'kari@example.com', 'hemmelig-123')
        self.fragment = self.person.password.rsplit('$', 1)[-1]

    def assertHidden(self, response):
        content = response.content if not response.streaming else b''.join(response.streaming_content)
        text = content.decode()
        self.assertNotIn(self.person.password, text)
        self.assertNotIn(self.fragment, text)
        self.assertNotIn(self.admin.password, text)

    def test_password_hashes_are_never_shown(self):
        response = self.page('auth_user')
        self.assertHidden(response)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'kari@example.com')
        grid = response.context['grid']
        self.assertEqual({row.cells[[c.name for c in grid.columns].index('password')].kind for row in grid.rows}, {'masked'})
        self.assertContains(response, 'masked')   # the column is there, its cells say so

    def test_a_masked_column_cannot_be_used_to_find_its_values(self):
        everyone = column(self.page('auth_user'), 'username')
        self.assertEqual(sorted(everyone), ['kari', 'root'])
        for query in ({'f_password': 'md5'}, {'f_password': self.fragment}, {'sort': 'password'}, {'sort': 'password', 'dir': 'desc'}):
            self.assertEqual(column(self.page('auth_user', **query), 'username'), everyone, query)   # ignored
        # The box is searched too, but a hash is never among the places it looks.
        for query in ({'q': self.fragment}, {'q': self.person.password}, {'q': 'md5'}):
            self.assertEqual(column(self.page('auth_user', **query), 'username'), [], query)

    def test_the_export_leaves_masked_columns_out(self):
        response = self.download('auth_user')
        self.assertHidden(self.download('auth_user'))
        rows = exported(response)
        self.assertNotIn('password', rows[0])
        self.assertEqual(sorted(row['username'] for row in rows), ['kari', 'root'])
        self.assertHidden(self.download('auth_user', f_password=self.fragment))

    @override_settings(DATABASE_VIEWER='core.test_database.MASKING_DESCRIPTION')
    def test_the_configuration_decides_what_is_masked(self):
        self.make_site(description='top secret wording')
        page = self.page('sites')
        self.assertNotContains(page, 'top secret wording')
        self.assertEqual(column(self.page('sites', q='secret'), 'name'), [])
        self.assertNotIn(b'secret', b''.join(self.download('sites').streaming_content))
        structure = {c.name: c for c in database.find('sites').structure().columns}
        self.assertTrue(structure['description'].masked)
        self.assertFalse(structure['name'].masked)


class ExportTests(DatabaseViewerTestCase):
    def setUp(self):
        super().setUp()
        self.bergen = self.make_site(latitude='60.391300', longitude='5.322100', altitude='-5.50', facilities={'tanks': 3},
                                     notes='Line one\nLine two, with a "quote"')
        self.tromso = self.make_site(name='Tromsø Grow-out', code='TG')
        self.tromso.soft_delete(self.admin)
        self.alta = self.make_site(name='Alta Smolt', code='AS')

    def test_it_is_a_streamed_csv_download(self):
        response = self.download('sites')
        self.assertTrue(response.streaming)
        self.assertEqual(response['Content-Type'], 'text/csv; charset=utf-8')
        self.assertEqual(response['Content-Disposition'], 'attachment; filename="sites.csv"')

    def test_it_holds_the_filtered_rows_as_stored(self):
        rows = exported(self.download('sites', sort='name', deleted='hide'))
        self.assertEqual([row['name'] for row in rows], ['Alta Smolt', 'Bergen Hatchery'])
        bergen = rows[1]
        self.assertEqual(bergen['id'], str(self.bergen.pk))
        self.assertEqual((bergen['latitude'], bergen['altitude'], bergen['is_deleted']), ('60.391300', '-5.50', 'false'))
        self.assertEqual(bergen['lokalitetsnummer'], '')                # NULL
        self.assertEqual(bergen['facilities'], '{"tanks": 3}')
        self.assertEqual(bergen['notes'], 'Line one\nLine two, with a "quote"')
        with connection.cursor() as cursor:
            cursor.execute('SELECT created_at::text FROM sites WHERE id = %s', [self.bergen.pk])
            self.assertEqual(bergen['created_at'], cursor.fetchone()[0])

    def test_it_follows_the_search_the_column_filters_and_the_deleted_rows(self):
        names = lambda **query: [row['name'] for row in exported(self.download('sites', **query))]
        self.assertEqual(sorted(names()), ['Alta Smolt', 'Bergen Hatchery', 'Tromsø Grow-out'])
        self.assertEqual(names(q='bergen'), ['Bergen Hatchery'])
        self.assertEqual(names(f_code='tg'), ['Tromsø Grow-out'])
        self.assertEqual(names(deleted='only'), ['Tromsø Grow-out'])
        self.assertEqual(names(f_name='zzz'), [])
        # The same rows the page shows for the same query.
        query = {'f_name': 'o', 'sort': 'code', 'dir': 'desc'}
        self.assertEqual(names(**query), column(self.page('sites', **query), 'name'))

    def test_it_is_capped(self):
        with mock.patch.object(dbgrid, 'EXPORT_LIMIT', 2):
            self.assertEqual(len(exported(self.download('sites'))), 2)

    def test_it_is_not_split_into_pages(self):
        Site.objects.bulk_create([Site(name=f'Site {i:03}', code=f'S{i:03}') for i in range(150)])
        self.assertEqual(len(exported(self.download('sites'))), 153)

    def test_text_a_spreadsheet_would_run_is_marked_but_numbers_are_not(self):
        self.make_site(name='=HYPERLINK("http://example.com")', code='X1', altitude='-7.00')
        rows = {row['code']: row for row in exported(self.download('sites'))}
        self.assertEqual(rows['X1']['name'], '\'=HYPERLINK("http://example.com")')
        self.assertEqual(rows['X1']['altitude'], '-7.00')

    def test_excel_can_read_its_encoding(self):
        self.assertTrue(b''.join(self.download('sites').streaming_content).startswith('﻿'.encode()))


class StructureTests(DatabaseViewerTestCase):
    def structure(self, name):
        return database.find(name).structure()

    def test_columns_agree_with_information_schema(self):
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT column_name, is_nullable, data_type, character_maximum_length, numeric_precision, numeric_scale
                FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = 'sites'
                ORDER BY ordinal_position
            """)
            expected = cursor.fetchall()
        columns = self.structure('sites').columns
        self.assertEqual([c.name for c in columns], [row[0] for row in expected])
        self.assertEqual([c.nullable for c in columns], [row[1] == 'YES' for row in expected])
        for found, (name, _, data_type, length, precision, scale) in zip(columns, expected):
            with self.subTest(column=name):
                self.assertEqual(found.type, {
                    'character varying': f'varchar({length})', 'numeric': f'numeric({precision},{scale})',
                    'timestamp with time zone': 'timestamptz', 'uuid': 'uuid', 'boolean': 'boolean', 'text': 'text',
                    'integer': 'integer', 'jsonb': 'jsonb', 'date': 'date',
                }[data_type])

    def test_columns_are_matched_with_the_model(self):
        columns = {c.name: c for c in self.structure('sites').columns}
        self.assertTrue(columns['id'].primary_key)
        self.assertEqual(columns['name'].field, Site._meta.get_field('name'))
        self.assertEqual(columns['created_by_id'].reference.table, 'auth_user')
        self.assertIsNone(columns['name'].reference)
        self.assertEqual(columns['version'].default, '')
        self.assertEqual(self.structure('auth_user').columns[0].default, 'identity')

    def test_constraints_and_indexes_are_what_the_database_has(self):
        structure = self.structure('sites')
        constraints = {c.name: c for c in structure.constraints}
        self.assertEqual(structure.constraints[0].kind, 'Primary key')
        self.assertEqual(constraints['sites_pkey'].definition, 'PRIMARY KEY (id)')
        self.assertEqual(constraints['chk_sites_latitude_range'].kind, 'Check')
        self.assertIn('latitude', constraints['chk_sites_latitude_range'].definition)
        self.assertTrue(any(c.kind == 'Foreign key' and 'REFERENCES auth_user(id)' in c.definition for c in structure.constraints))
        indexes = {i.name: i for i in structure.indexes}
        self.assertTrue(indexes['uq_sites_code_live'].unique)
        self.assertIn('WHERE', indexes['uq_sites_code_live'].definition)    # a partial index, as the model declares
        self.assertFalse(next(i for i in structure.indexes if i.name.startswith('sites_type')).unique)
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM pg_indexes WHERE tablename = 'sites'")
            self.assertEqual(len(structure.indexes), cursor.fetchone()[0])

    def test_relationships_run_both_ways(self):
        sites = self.structure('sites')
        self.assertTrue({('production_departments', 'site_id'), ('site_contacts', 'site_id')}
                        <= {(r.table, r.other_column) for r in sites.referenced_by})
        self.assertTrue(all(r.linked and r.enforced for r in sites.referenced_by))
        departments = self.structure('production_departments')
        self.assertTrue({('site_id', 'sites', 'id'), ('manager_id', 'auth_user', 'id'), ('created_by_id', 'auth_user', 'id')}
                        <= {(r.column, r.table, r.other_column) for r in departments.references})

    def test_a_link_the_database_does_not_check_says_so(self):
        users = self.structure('auth_user')
        audit = next(r for r in users.referenced_by if r.table == 'audit_log')
        self.assertFalse(audit.enforced)
        self.assertTrue(audit.linked)
        page = self.page('auth_user')
        self.assertContains(page, 'not enforced by the database')
        unlisted = [r for r in users.referenced_by if r.table == 'django_admin_log']
        self.assertTrue(unlisted and not unlisted[0].linked)   # an app the viewer does not show: named, not linked

    def test_the_page_names_the_model_and_its_app(self):
        page = self.page('sites')
        self.assertContains(page, '<code>farm.Site</code> of the <code>farm</code> app')
        self.assertContains(page, 'uq_sites_code_live')
        self.assertContains(page, 'varchar(150)')
