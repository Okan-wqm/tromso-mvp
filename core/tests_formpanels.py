"""The forms whose page is a template of their own, in the new look (core/formpanels.py, Resource.next_panels): each says,
new, editing and refused, everything its classic page says (core.pagesays) in English, Norwegian and Turkish; a list
saved apart (core.crud.RowList) posts, from the names and values of its props alone, what its classic form posts, and
saves; and the withdrawal guard's question a save asks first is drawn whole (its warnings, its box and its fingerprint,
or why a second person must approve) and going on through it saves, on a record's own form and on a list."""
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse

from farm.tests.test_withdrawal_guard import GuardTestCase

from .crud import Resource
from .pagesays import unsaid
from .tests_formprops import MANIFEST, props_of
from .test_world import MOMENT, record_of, refused_rows_data, world

LANGUAGES = ('en', 'nb', 'tr')


def ported():
    """The tabs with a form template of their own that the island draws (their next_panels words it)."""
    return [resource for resource in Resource.registry if resource.form_class is not None
            and resource.form_template != 'crud/form.html'
            and resource.next_panels.__func__ is not Resource.next_panels.__func__]


def labels_of(props):
    """What the old page says twice as layout, a tab's label on its tab and as its panel's heading: said once is enough. Only
    the record's tab labels and the panels' own labels (review B6): a field or a column called like a tab is counted."""
    return {tab['label'] for tab in props['form']['tabs']} | {each['label'] for each in props['panels'] if each['label']}


def apart(props):
    """What the island says from one prop where the old page repeats it, each derived from the props so it hides nothing else:
    a history entry's words after the person's name and the separator before the time ('tarafından ·' in Turkish: one
    run on the old page, the words then ' · ' on the island), and the history's word for an empty value ('tom'), which
    the island draws for each change from its one prop."""
    if not props.get('history'):
        return set()
    return {f"{entry['by']['after']} ·" for entry in props['history']['entries'] if entry['by']['after']} | {
        props['history']['empty_value']}


def value_of(field):
    """What the island posts for one field of the payload (frontend/islands/pages/RecordForm.tsx FieldOf), as its controls
    are drawn: a list of values, none for a box not ticked or a control switched off."""
    widget = field['widget']
    if field['disabled'] or widget['kind'] in ('output', 'file', 'matrix', 'links'):
        return []
    if widget['kind'] in ('select', 'multiselect', 'checks', 'radio'):
        chosen = [option['value'] for group in widget.get('groups', []) for option in group['options'] if option['selected']]
        return chosen or ([''] if widget['kind'] == 'select' else [])
    if widget['kind'] in ('checkbox', 'acknowledge'):
        return [str(widget['value']) if widget['value'] not in (None, True, '') else 'on'] if widget['attrs'].get('checked') \
            else []
    return ['' if widget['value'] is None else str(widget['value'])]


def posted(fields, hidden=()):
    """{name: [values]} the island posts for `fields` and `hidden` inputs."""
    data = {}
    for each in hidden:
        data.setdefault(each['name'], []).append('' if each['value'] is None else str(each['value']))
    for field in fields:
        values = value_of(field)
        if values:
            data.setdefault(field['widget']['name'], []).extend(values)
        if field['initial']:
            data.setdefault(field['initial']['name'], []).extend(field['initial']['values'])
    return data


def form_posted(props):
    form = props['form']
    return posted([field for tab in form['tabs'] for fieldset in tab['fieldsets'] for field in fieldset['fields']],
                  form['hidden'])


def rows_blocks(props):
    return [block for each in props['panels'] for block in each['blocks'] if block['kind'] == 'rows']


def rows_posted(block):
    """What a list's form posts as the island draws it: the management form (its total the rows drawn), the record's
    version, every row's hidden and visible fields."""
    grid = block['grid']
    data = {each['name']: [str(each['value'])] for each in grid['management']}
    data[f"{grid['prefix']}-TOTAL_FORMS"] = [str(len(grid['rows']))]
    if block['version'] is not None:
        data['version'] = [str(block['version'])]
    for row in grid['rows']:
        data.update(posted([field for cell in row['cells'] for field in cell], row['hidden']))
    return data


def own_forms(props):
    return [block for each in props['panels'] for block in each['blocks'] if block['kind'] == 'form']


def form_block_posted(block, button=None):
    """What a form of its own posts as the island draws it (core.formpanels.form): its hidden fields, its fields, each
    grid's management form (its total the rows drawn), rows and cells, and the button pressed (name and value)."""
    data = {}
    for each in block['hidden']:
        data[each['name']] = ['' if each['value'] is None else str(each['value'])]
    for part in block['parts']:
        if part['kind'] == 'fields':
            data.update(posted(part['fields']))
        elif part['kind'] == 'grid':
            data.update({each['name']: [str(each['value'])] for each in part['management']})
            data[f"{part['prefix']}-TOTAL_FORMS"] = [str(len(part['rows']))]
            for row in part['rows']:
                data.update(posted([field for cell in row['cells'] for field in cell], row['hidden']))
    if button and button['name']:
        data[button['name']] = [button['value']]
    return data


@override_settings(ISLANDS_MANIFEST=MANIFEST, ALLOWED_HOSTS=['localhost', 'testserver'])
class PortedFormTests(TestCase):
    def setUp(self):
        clock = mock.patch('django.utils.timezone.now', return_value=MOMENT)
        clock.start()
        self.addCleanup(clock.stop)
        self.admin = get_user_model().objects.create_superuser('test.admin', 'test.admin@example.com', 'x')
        self.made = world(self.admin)
        self.client.force_login(self.admin)

    def look(self, look):
        self.client.get(reverse('home'), {'ui': look})

    def both(self, method, url, data=None):
        """The classic answer and the new one, the same request in each look."""
        answers = []
        for look in ('classic', 'next'):
            self.look(look)
            answers.append(getattr(self.client, method)(url, data) if data is not None else getattr(self.client, method)(url))
        return answers

    def test_the_test_world_saved_every_list_it_made(self):
        self.assertTrue(all(each.endswith(': 302') for each in self.made if ' of ' in each), self.made)

    def test_every_ported_form_says_all_its_classic_page_says_new_and_editing_in_three_languages(self):
        tabs = ported()
        self.assertGreaterEqual(len(tabs), 16, tabs)
        for resource in tabs:
            # new, and every record of the test world (a lice report and a biomass report have other lists)
            urls = [('new', reverse(resource.url_name('create')))] if resource.allows('add') else []
            if resource.allows('change'):
                urls += [(f'edit {record.pk}', reverse(resource.url_name('edit'), args=[record.pk]))
                         for record in resource.queryset().order_by('pk')[:5]]
            self.assertTrue(urls, resource)
            for language in LANGUAGES:
                self.client.cookies['django_language'] = language
                for what, url in urls:
                    with self.subTest(tab=resource.__name__, page=what, language=language):
                        old, new = self.both('get', url)
                        self.assertEqual(old.status_code, 200)
                        props = props_of(new.content.decode(), 'record-form')
                        self.assertIsNotNone(props, 'the island draws it')
                        self.assertNotIn('class="record-form"', new.content.decode())
                        self.assertEqual(unsaid(old.content.decode(), props, new_html=new.content.decode(),
                                                once=labels_of(props), ignore=apart(props)), [])

    def test_every_list_refused_says_what_the_classic_page_says_and_opens_on_its_tab(self):
        for resource in ported():
            record = record_of(resource)
            for rows in resource.row_lists:
                if record is None or not rows.applies_to(record) or not resource.allows('change'):
                    continue
                data = refused_rows_data(rows, record)
                url = reverse(resource.url_name(rows.key), args=[record.pk])
                with self.subTest(tab=resource.__name__, rows=rows.key):
                    old, new = self.both('post', url, data)
                    self.assertIn(old.status_code, (200, 422))
                    props = props_of(new.content.decode(), 'record-form')
                    self.assertIsNotNone(props)
                    self.assertEqual(props['openTab'], rows.tab)
                    [block] = [block for each in props['panels'] if each['key'] == rows.tab for block in each['blocks']
                               if block['kind'] == 'rows']
                    refused = block['grid']['errors'] or any(
                        field['errors'] for row in block['grid']['rows'] for cell in row['cells'] for field in cell)
                    self.assertTrue(refused, 'the refusal is in the list')
                    self.assertEqual(unsaid(old.content.decode(), props, new_html=new.content.decode(),
                                            once=labels_of(props), ignore=apart(props)), [])

    def test_every_list_posts_from_its_props_what_it_holds_and_saves(self):
        saved = 0
        for resource in ported():
            record = record_of(resource)
            if record is None or not resource.allows('change'):
                continue
            self.look('next')
            props = props_of(self.client.get(reverse(resource.url_name('edit'), args=[record.pk])).content.decode(),
                             'record-form')
            for block in rows_blocks(props):
                with self.subTest(tab=resource.__name__, action=block['action']):
                    rows = next(each for each in resource.row_lists
                                if block['action'] == reverse(resource.url_name(each.key), args=[record.pk]))
                    before = rows.summary(record)
                    response = self.client.post(block['action'], rows_posted(block))
                    self.assertEqual(response.status_code, 302, response.content.decode()[:2000])
                    self.assertEqual(rows.summary(record), before)
                    saved += 1
        self.assertGreaterEqual(saved, 9)

    def test_a_contact_added_from_the_empty_row_is_saved_and_the_one_primary_rule_holds(self):
        from farm.models import Site
        north = Site.objects.get(code='TSN')
        self.look('next')
        props = props_of(self.client.get(reverse('farm:site_edit', args=[north.pk])).content.decode(), 'record-form')
        [contacts] = [each for each in props['panels'] if each['key'] == 'contact']
        self.assertEqual(contacts['tab'], 'contact')                     # on the site's own Contact tab
        [block] = [each for each in contacts['blocks'] if each['kind'] == 'rows']
        data = rows_posted(block)
        index = len(block['grid']['rows'])
        for field in [field for cell in block['grid']['empty']['cells'] for field in cell]:
            name = field['widget']['name'].replace('__prefix__', str(index))
            data[name] = {'name': ['Test Second'], 'email': ['second@example.com'], 'is_primary': ['on']}.get(
                name.rsplit('-', 1)[-1], [''])
        data[f"{block['grid']['prefix']}-TOTAL_FORMS"] = [str(index + 1)]
        refused = self.client.post(block['action'], {key: value for key, value in data.items()
                                                     if not key.endswith('-DELETE')})
        props = props_of(refused.content.decode(), 'record-form')
        [block] = rows_blocks(props)
        self.assertTrue(block['grid']['errors'])                       # two primaries: said on the list
        data[f'contacts-{index}-is_primary'] = []
        self.assertEqual(self.client.post(block['action'], {key: value for key, value in data.items() if value != []
                                                            and not key.endswith('-DELETE')}).status_code, 302)
        self.assertEqual(sorted(north.contacts.values_list('name', flat=True)), ['Test Contact', 'Test Second'])

    def test_a_started_checklist_is_read_only_with_who_and_when(self):
        from django.utils import timezone

        from tasks.models import Task
        task = Task.objects.get(title='Test task')
        line = task.checklist.order_by('pk').first()
        line.done_at, line.done_by = timezone.now(), self.admin
        line.save()
        url = reverse('tasks:task_edit', args=[task.pk])
        old, new = self.both('get', url)
        props = props_of(new.content.decode(), 'record-form')
        [checklist] = [each for each in props['panels'] if each['key'] == 'checklist']
        self.assertEqual([block['kind'] for block in checklist['blocks']], ['help', 'checks'])
        self.assertEqual([line['done'] for line in checklist['blocks'][1]['lines']], [True, False])
        self.assertEqual(unsaid(old.content.decode(), props, new_html=new.content.decode(), once=labels_of(props), ignore=apart(props)), [])

    def test_a_feeding_table_and_a_design_post_from_their_props_what_they_hold_and_save(self):
        from experiments.models import Experiment
        from farm.models import FeedingProtocol
        self.assertTrue(all(each.endswith(': 302') for each in self.made if each.startswith(('table', 'experiment',
                                                                                              'design'))), self.made)
        protocol = FeedingProtocol.objects.get(name='Test grow-out')
        trial = Experiment.objects.get(name='Test trial')
        for url, rates in ((reverse('farm:feedingprotocol_edit', args=[protocol.pk]), True),
                           (reverse('experiments:experiment_edit', args=[trial.pk]), False)):
            with self.subTest(url=url):
                self.look('next')
                props = props_of(self.client.get(url).content.decode(), 'record-form')
                [block] = own_forms(props)[:1]
                [save] = [each for each in block['actions'] if each['primary']]
                response = self.client.post(block['action'], form_block_posted(block, save))
                self.assertEqual(response.status_code, 302, response.content.decode()[:3000])
        self.assertEqual(protocol.bands.count(), 2)
        self.assertEqual(sorted(trial.groups.values_list('name', flat=True)), ['Test control'])

    def test_a_field_that_changes_the_grid_renders_it_again_as_a_draft_saving_nothing(self):
        from farm.models import FeedingProtocol
        protocol = FeedingProtocol.objects.get(name='Test grow-out')
        url = reverse('farm:feedingprotocol_edit', args=[protocol.pk])
        self.look('next')
        [block] = own_forms(props_of(self.client.get(url).content.decode(), 'record-form'))
        data = {**form_block_posted(block), 'temperatures': ['8 12 16'], '_draft': ['temperatures']}
        props = props_of(self.client.post(block['action'], data).content.decode(), 'record-form')
        self.assertEqual(props['openTab'], 'table')
        [block] = own_forms(props)
        [grid] = [part for part in block['parts'] if part['kind'] == 'grid']
        self.assertEqual(len(grid['columns']), 8)                       # five, and an SFR column a temperature
        self.assertEqual(4,
                         sum(band.rates.count() for band in protocol.bands.all()))   # nothing saved

    def test_the_card_designer_keeps_its_classic_page(self):
        self.look('next')
        page = self.client.get(reverse('monitoring:cardtemplate_create')).content.decode()
        self.assertIsNone(props_of(page, 'record-form'))


class Asked:
    """A change the guard asks about, as farm.health.withdrawal.Change gives it to the page."""

    def __init__(self, second_person=''):
        self.fingerprint, self.second_person = 'f00dfeed', second_person

    def messages(self):
        return ['Test harvest of 23.11.2026 lies inside this withdrawal (end unknown).']


@override_settings(ISLANDS_MANIFEST=MANIFEST, ALLOWED_HOSTS=['localhost', 'testserver'])
class EveryQuestionTabTests(TestCase):
    """Every tab whose save may ask the guard's question (`question_template`) draws it in the new look, as the classic page
    says it: the warnings and the box with the change's fingerprint, or why a second person must approve and no box."""

    def setUp(self):
        clock = mock.patch('django.utils.timezone.now', return_value=MOMENT)
        clock.start()
        self.addCleanup(clock.stop)
        self.admin = get_user_model().objects.create_superuser('test.admin', 'test.admin@example.com', 'x')
        world(self.admin)
        self.client.force_login(self.admin)

    def test_the_question_is_drawn_whole_on_every_tab_that_may_ask_it(self):
        from farm.health.withdrawal import FIELD
        asking = [resource for resource in Resource.registry if resource.question_template and resource.allows('change')]
        self.assertGreaterEqual(len(asking), 5)
        for resource in asking:
            record = record_of(resource)
            self.assertIsNotNone(record, resource)
            url = reverse(resource.url_name('edit'), args=[record.pk])
            for second in ('', 'A second person must approve this change.'):
                def refuse(cls, request, read, write, seen, second=second):
                    raise _refusal(second)
                with self.subTest(tab=resource.__name__, second_person=bool(second)), \
                        mock.patch.object(resource, 'edited', classmethod(refuse)):
                    self.client.get(url, {'ui': 'next'})
                    props = props_of(self.client.get(url).content.decode(), 'record-form')
                    self.assertIsNotNone(props, 'the island draws the tab')
                    data = form_posted(props)
                    old, new = (self.client.post(f'{url}?ui={look}', data) for look in ('classic', 'next'))
                    self.assertEqual((old.status_code, new.status_code), (422, 422), old.content.decode()[:3000])
                    props = props_of(new.content.decode(), 'record-form')
                    question = props['question']
                    self.assertEqual(question['messages'], Asked().messages())
                    if second:
                        self.assertIsNone(question['box'])
                        self.assertEqual(question['secondPerson'], second)
                    else:
                        self.assertEqual((question['box']['name'], question['box']['value']), (FIELD, 'f00dfeed'))
                    self.assertEqual(unsaid(old.content.decode(), props, new_html=new.content.decode(),
                                            once=labels_of(props), ignore=apart(props)), [])


def _refusal(second):
    error = ValidationError(['Tick the box to go on despite these warnings.'])
    error.change = Asked(second)
    return error


@override_settings(ISLANDS_MANIFEST=MANIFEST, ALLOWED_HOSTS=['localhost', 'testserver'])
class GuardQuestionSavesTests(GuardTestCase):
    """The guard's real question in the new look: a feed made medicated over a recorded harvest (the feed's own form,
    `question_template`) and a medicine's withdrawal made longer over one (its list): refused with the question, and saved
    with the fingerprint the island's box posts."""

    def setUp(self):
        super().setUp()
        # a person who may edit feeds and medicines (the guard's own tests' user records fish, not reference data)
        self.client.force_login(get_user_model().objects.create_superuser('test.keeper', 'test.keeper@example.com', 'x'))
        self.client.get(reverse('home'), {'ui': 'next'})

    def test_a_feed_made_medicated_asks_on_its_own_form_and_saves_past_the_box(self):
        from farm.feeding import services as feeding_services
        from farm.models import Feed, WithdrawalAcknowledgement
        from decimal import Decimal
        feed = Feed.objects.create(name='Grower T', code='GRT', feed_type='grower')
        self.harvest(2)                  # first: fed fish are asked about at a harvest (fasting), not after it
        feeding_services.record_feeding(self.user, unit=self.t1, day=self.day(4), feed=feed, amount_kg=Decimal('2'))
        url = reverse('farm:feed_edit', args=[feed.pk])
        props = props_of(self.client.get(url).content.decode(), 'record-form')
        data = {**form_posted(props), 'feed_type': ['medicated']}
        refused = self.client.post(url, data)
        self.assertEqual(refused.status_code, 422)
        props = props_of(refused.content.decode(), 'record-form')
        self.assertIn('lies inside this withdrawal', ' '.join(props['question']['messages']))
        self.assertEqual(Feed.objects.get(pk=feed.pk).feed_type, 'grower')
        box = props['question']['box']
        self.assertEqual(self.client.post(url, {**form_posted(props), 'feed_type': ['medicated'],
                                                box['name']: [box['value']]}).status_code, 302)
        self.assertEqual(Feed.objects.get(pk=feed.pk).feed_type, 'medicated')
        self.assertTrue(WithdrawalAcknowledgement.objects.exists())

    def test_a_medicine_row_made_longer_asks_on_its_list_and_saves_past_the_box(self):
        from farm.models import WithdrawalAcknowledgement
        bath = self.medicine(days=1)
        self.treat(bath, 5, 5)
        self.harvest(2)
        props = props_of(self.client.get(reverse('farm:medicine_edit', args=[bath.pk])).content.decode(), 'record-form')
        [block] = rows_blocks(props)
        data = rows_posted(block)
        [days] = [name for name in data if name.endswith('-days')]
        data[days] = ['7']
        refused = self.client.post(block['action'], data)
        self.assertEqual(refused.status_code, 422)
        props = props_of(refused.content.decode(), 'record-form')
        self.assertEqual(props['openTab'], 'withdrawal')
        [block] = rows_blocks(props)
        self.assertIn('lies inside this withdrawal', ' '.join(block['question']['messages']))
        self.assertEqual(list(bath.withdrawals.values_list('days', flat=True)), [1])
        box = block['question']['box']
        self.assertEqual(self.client.post(block['action'], {**data, box['name']: [box['value']]}).status_code, 302)
        self.assertEqual(list(bath.withdrawals.values_list('days', flat=True)), [7])
        self.assertEqual(WithdrawalAcknowledgement.objects.get().record_type, 'medicine')
