"""Languages: which one a request is shown in, how the choice is kept, that every page renders in each
language, numbers and dates, emails, and that the activity log is English at rest."""
import re
from datetime import datetime, timezone as utc
from decimal import Decimal
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core import mail
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from farm.models import (Equipment, EquipmentSystem, EquipmentType, FeederCalibration, HandlingRule,
                         ProductionDepartment, SiteContact, Site, SlaughterFacility, Species, System, Tank, WaterLimit,
                         WaterMeasurement)
from farm.tests.helpers import SITE_MANAGER, contacts_data, role, site_data

from .audit import message
from .models import AuditLog, Profile
from .tests import perms, user_data

COOKIE = settings.LANGUAGE_COOKIE_NAME
LANGUAGES = [code for code, _ in settings.LANGUAGES]


def setUpModule():
    call_command('compile_catalogs', verbosity=0)


def lang_of(response):
    return re.search(r'<html lang="([\w-]+)"', response.content.decode()).group(1)


class NegotiationTests(TestCase):
    """A visitor's language: cookie, then Accept-Language, then English."""

    def get_login(self, **headers):
        return self.client.get(reverse('login'), headers=headers)

    def test_a_new_visitor_gets_the_language_of_the_browser_or_english(self):
        for header, expected, heading in [
            ('tr', 'tr', '<h1>Giriş yap</h1>'), ('nb-NO,nb;q=0.9', 'nb', '<h1>Logg inn</h1>'),
            ('en-US', 'en', '<h1>Sign in</h1>'), ('de', 'en', '<h1>Sign in</h1>'), ('', 'en', '<h1>Sign in</h1>'),
        ]:
            with self.subTest(header=header):
                response = self.get_login(**{'Accept-Language': header} if header else {})
                self.assertEqual(lang_of(response), expected)
                self.assertContains(response, heading)
                self.assertEqual(response['Content-Language'], expected)

    def test_the_switcher_sets_the_cookie_and_the_cookie_wins_over_the_browser(self):
        response = self.client.post(reverse('core:set_language'), {'language': 'nb', 'next': reverse('login')})
        self.assertRedirects(response, reverse('login'), fetch_redirect_response=False)
        self.assertEqual(response.cookies[COOKIE].value, 'nb')
        self.assertEqual(response.cookies[COOKIE]['max-age'], settings.LANGUAGE_COOKIE_AGE)
        page = self.get_login(**{'Accept-Language': 'tr'})
        self.assertEqual(lang_of(page), 'nb')
        self.assertContains(page, '<h1>Logg inn</h1>')

    def test_the_sign_in_pages_offer_the_switcher(self):
        for name in ('login', 'password_reset', 'password_reset_done', 'password_reset_complete'):
            response = self.client.get(reverse(name))
            self.assertContains(response, 'action="%s"' % reverse('core:set_language'), msg_prefix=name)
            for code in LANGUAGES:
                self.assertContains(response, 'name="language" value="%s"' % code, msg_prefix=name)
            self.assertContains(response, 'aria-current="true"', count=1, msg_prefix=name)

    def test_an_unknown_language_or_a_foreign_next_page_is_ignored(self):
        response = self.client.post(reverse('core:set_language'), {'language': 'xx', 'next': 'https://evil.example/'})
        self.assertNotIn(COOKIE, response.cookies)
        self.assertRedirects(response, '/', fetch_redirect_response=False)

    def test_the_language_switch_changes_nothing_with_a_get(self):
        response = self.client.get(reverse('core:set_language'), {'language': 'tr', 'next': '/'})
        self.assertNotIn(COOKIE, response.cookies)


class AccountLanguageTests(TestCase):
    """For a signed-in person the language is saved on the account, so it follows them to any device."""

    def setUp(self):
        self.user = get_user_model().objects.create_user('ali', 'ali@example.com', 'x')
        self.client.force_login(self.user)

    def test_the_switcher_also_saves_the_language_on_the_account(self):
        response = self.client.post(reverse('core:set_language'), {'language': 'tr', 'next': '/'})
        self.assertEqual(response.cookies[COOKIE].value, 'tr')
        self.assertEqual(Profile.objects.get(user=self.user).language, 'tr')
        self.client.post(reverse('core:set_language'), {'language': 'nb', 'next': '/'})
        self.assertEqual(Profile.objects.get(user=self.user).language, 'nb')     # one profile, updated
        self.assertEqual(Profile.objects.count(), 1)

    def test_the_account_language_applies_on_another_device(self):
        Profile.objects.create(user=self.user, language='nb')
        response = self.client.get(reverse('home'), headers={'Accept-Language': 'tr'})
        self.assertEqual(lang_of(response), 'nb')
        self.assertContains(response, 'Velkommen, ali')
        self.assertContains(response, 'aria-current="true"', count=1)

    def test_a_person_without_a_saved_language_follows_the_cookie_then_the_browser(self):
        self.assertEqual(lang_of(self.client.get(reverse('home'), headers={'Accept-Language': 'tr'})), 'tr')
        self.client.cookies[COOKIE] = 'nb'
        self.assertEqual(lang_of(self.client.get(reverse('home'), headers={'Accept-Language': 'tr'})), 'nb')

    def test_a_saved_language_that_is_no_longer_offered_is_ignored(self):
        Profile.objects.create(user=self.user, language='de')
        self.assertEqual(lang_of(self.client.get(reverse('home'))), 'en')

    def test_the_profile_goes_with_the_user(self):
        Profile.objects.create(user=self.user, language='tr')
        self.user.delete()
        self.assertFalse(Profile.objects.exists())


class PagesInEveryLanguageTests(TestCase):
    """Every page and dialog renders in each language, with no placeholder left over."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser('root', 'root@example.com', 'x')
        cls.site = Site.objects.create(name='Bergen', code='BG', area_m2=Decimal('50000.5'))
        SiteContact.objects.create(site=cls.site, name='Kari', is_primary=True)
        cls.department = ProductionDepartment.objects.create(
            name='Hall A', code='HA', site=cls.site, capacity=Decimal('12.5'))
        cls.system = System.objects.create(name='RAS 1', code='R1', site=cls.site,
                                           production_department=cls.department,
                                           total_volume_m3=Decimal('1500'))
        cls.feeder = Equipment.objects.create(
            name='Feeder 1', code='F1', production_department=cls.department,
            equipment_type=EquipmentType.objects.get(code='feeder-automatic'),
            specifications={'capacity': 50, 'siloVolume': 200.5, 'controlType': 'timer', 'autoFilling': True})
        EquipmentSystem.objects.create(equipment=cls.feeder, system=cls.system, is_primary=True, role='feeding')
        FeederCalibration.objects.create(equipment=cls.feeder, feed_size_mm=Decimal('3'), grams_per_dispensing=25,
                                         silo_capacity_kg=Decimal('250.5'))
        cls.unit = Tank.objects.create(
            name='Pond 1', code='P1', kind='pond', production_department=cls.department, system=cls.system,
            water_type='brackish', pond_type='lined', liner_type='hdpe', liner_thickness_mm=Decimal('1.5'),
            surface_area_m2=Decimal('2500.5'), depth=Decimal('1.5'), water_depth=Decimal('1.25'),
            max_density_kg_m3=Decimal('3'))
        cls.species = Species.objects.create(common_name='Atlantic salmon', scientific_name='Salmo salar', code='SAL',
                                             freshwater=True, saltwater=True)
        cls.water_limit = WaterLimit.objects.create(species=cls.species, parameter='ph', critical_low=Decimal('6.5'))
        cls.sample = WaterMeasurement.objects.create(unit=cls.unit, measured_at=cls.unit.created_at, source='manual',
                                                     ph=Decimal('7.25'), tan_mg_l=Decimal('0.5'),
                                                     temperature_c=Decimal('9.5'), oxygen_mg_l=Decimal('10.5'))
        cls.facility = SlaughterFacility.objects.create(name='Fjord Slakteri', approval_number='M123')
        cls.rule = HandlingRule.objects.get(kind='harvest', species__isnull=True)
        cls.role = Group.objects.create(name='Feeder')
        cls.role.permissions.set(Permission.objects.filter(codename='view_site'))
        cls.admin.groups.add(cls.role)
        AuditLog.objects.create(user=cls.admin, user_name='root', action='create', entity_type='site',
                                entity_id=str(cls.site.pk), entity_label='Bergen (BG)',
                                changes={'Site name': [None, 'Bergen'], 'Status': [None, message('Active')]})

    def urls(self):
        pages = [
            reverse('home'), reverse('production_home'), reverse('password_change'), reverse('core:activity_log'),
            reverse('core:group_list'), reverse('core:group_create'), reverse('core:group_edit', args=[self.role.pk]),
            reverse('core:group_delete', args=[self.role.pk]),
            reverse('core:user_list'), reverse('core:user_create'), reverse('core:user_edit', args=[self.admin.pk]),
            reverse('core:database'), reverse('core:database_table', args=['sites']),
        ]
        water, sample = reverse('farm:water'), reverse('farm:water_record')
        pages += [water, f'{water}?view=history', f'{water}?unit={self.unit.pk}', sample,
                  f'{sample}?unit={self.unit.pk}',
                  f"{reverse('farm:water_round')}?site={self.site.pk}",
                  reverse('farm:water_void', args=[self.sample.pk])]
        pages += [reverse('farm:harvests'), reverse('farm:handlingplanitem_list'),
                  reverse('farm:handlingplanitem_create'), f"{reverse('farm:handlingplanitem_create')}?kind=transport",
                  reverse('farm:productionplan_list'), reverse('farm:productionplan_create')]
        for resource, record in (('site', self.site), ('productiondepartment', self.department), ('system', self.system),
                                 ('equipment', self.feeder), ('tank', self.unit), ('species', self.species),
                                 ('waterlimit', self.water_limit), ('slaughterfacility', self.facility),
                                 ('handlingrule', self.rule)):
            pages += [reverse(f'farm:{resource}_list'), reverse(f'farm:{resource}_create'),
                      reverse(f'farm:{resource}_edit', args=[record.pk]),
                      reverse(f'farm:{resource}_delete', args=[record.pk])]
        return pages

    def test_every_page_and_dialog_renders_in_each_language(self):
        for language in LANGUAGES:
            Profile.objects.update_or_create(user=self.admin, defaults={'language': language})
            self.client.force_login(self.admin)
            for url in self.urls():
                for headers in ({}, {'X-Modal': '1'}):
                    with self.subTest(language=language, url=url, modal=bool(headers)):
                        response = self.client.get(url, headers=headers)
                        self.assertEqual(response.status_code, 200)
                        self.assertNotIn('%(', response.content.decode())
                        self.assertEqual(response['Content-Language'], language)
                        if not headers:
                            self.assertEqual(lang_of(response), language)

    def test_the_sign_in_and_password_pages_render_in_each_language(self):
        token_page = reverse('password_reset_confirm', args=['x', 'y'])
        for language in LANGUAGES:
            self.client.cookies[COOKIE] = language
            for url in (reverse('login'), reverse('password_reset'), reverse('password_reset_done'),
                        reverse('password_reset_complete'), token_page):
                with self.subTest(language=language, url=url):
                    response = self.client.get(url)
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(lang_of(response), language)
                    self.assertNotIn('%(', response.content.decode())

    def test_each_language_shows_its_own_words(self):
        expected = {'en': ('Sites', 'Activity log', 'Sign out'), 'tr': ('Sahalar', 'Etkinlik günlüğü', 'Çıkış yap'),
                    'nb': ('Lokaliteter', 'Aktivitetslogg', 'Logg ut')}
        for language, words in expected.items():
            Profile.objects.update_or_create(user=self.admin, defaults={'language': language})
            self.client.force_login(self.admin)
            home = self.client.get(reverse('home'))
            for word in words:
                self.assertContains(home, word, msg_prefix=language)

    def test_the_database_viewer_chrome_is_translated_but_names_are_not(self):
        for language, tab, empty in [('tr', 'Yapı', 'Eşleşen satır yok.'), ('nb', 'Struktur', 'Ingen rader samsvarer.')]:
            Profile.objects.update_or_create(user=self.admin, defaults={'language': language})
            self.client.force_login(self.admin)
            page = self.client.get(reverse('core:database_table', args=['sites']), {'q': 'no such site'})
            self.assertContains(page, tab)
            self.assertContains(page, empty.split('.')[0])
            self.assertContains(page, '<span class="mono">sites</span>', html=True)      # a table's name is the database's

    def test_the_texts_the_typescript_shows_come_from_the_page(self):
        Profile.objects.update_or_create(user=self.admin, defaults={'language': 'tr'})
        self.client.force_login(self.admin)
        home = self.client.get(reverse('home'))
        self.assertContains(home, 'data-forbidden="Bunu yapma izniniz yok."')
        self.assertContains(home, 'data-label-collapse="Menüyü daralt" data-label-expand="Menüyü genişlet"')
        self.client.logout()
        self.client.cookies[COOKIE] = 'nb'
        self.assertContains(self.client.get(reverse('login')), 'data-label-show="Vis" data-label-hide="Skjul"')


class FormsAndMessagesTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('ali', 'ali@example.com', 'x')
        self.user.groups.add(role('Site manager', *SITE_MANAGER))
        self.client.force_login(self.user)

    def in_language(self, language):
        Profile.objects.update_or_create(user=self.user, defaults={'language': language})

    def test_flash_messages_and_errors_are_in_the_language(self):
        self.in_language('tr')
        response = self.client.post(reverse('farm:site_create'), site_data(name='Bergen', code='bh'), follow=True)
        self.assertContains(response, 'Saha “Bergen (BH)” oluşturuldu.')
        invalid = self.client.post(reverse('farm:site_create'), site_data(name='', code='x'))
        self.assertEqual(invalid.context['form'].errors['code'], ['Kod en az 2 karakter olmalı.'])
        self.assertEqual(invalid.context['form'].errors['name'], ['Bu alan zorunludur.'])      # Django's own
        self.in_language('nb')
        response = self.client.post(reverse('farm:site_create'), site_data(name='Tromsø', code='ts'), follow=True)
        self.assertContains(response, 'Lokalitet «Tromsø (TS)» ble opprettet.')

    def test_counted_messages_follow_each_languages_plural_rule(self):
        site = Site.objects.create(name='Bergen', code='BG')
        url = reverse('farm:site_contacts', args=[site.pk])
        rows = [{'name': 'Kari'}, {'name': 'Ola'}]
        for language, one, two in [('en', '1 contact saved.', '2 contacts saved.'),
                                   ('nb', '1 kontaktperson lagret.', '2 kontaktpersoner lagret.'),
                                   ('tr', '1 kişi kaydedildi.', '2 kişi kaydedildi.')]:
            self.in_language(language)
            self.assertContains(self.client.post(url, contacts_data(rows[:1], record=site), follow=True), one,
                                msg_prefix=language)
            self.assertContains(self.client.post(url, contacts_data(rows, record=site), follow=True), two,
                                msg_prefix=language)

    def test_quantities_are_shown_and_read_the_way_the_language_writes_them(self):
        site = Site.objects.create(name='Bergen', code='BG', area_m2=Decimal('50000.5'),
                                   latitude=Decimal('60.3913'), longitude=Decimal('5.3221'))
        edit, listing = reverse('farm:site_edit', args=[site.pk]), reverse('farm:site_list')
        for language, area_input, latitude_input, area_shown in [
            ('en', '50000.50', '60.391300', '50,000.50'), ('tr', '50000,50', '60,391300', '50.000,50'),
            ('nb', '50000,50', '60,391300', '50\xa0000,50'),
        ]:
            with self.subTest(language=language):
                self.in_language(language)
                page = self.client.get(edit)
                self.assertContains(page, f'name="area_m2" value="{area_input}"')
                self.assertContains(page, f'name="latitude" value="{latitude_input}"')
                self.assertContains(page, 'inputmode="decimal"')
                self.assertContains(self.client.get(listing), f'{area_shown} m²')

    def test_quantities_typed_with_a_decimal_comma_are_read_correctly(self):
        for language, area, latitude, expected in [
            ('nb', '1234,5', '60,3913', Decimal('1234.50')), ('tr', '1234,5', '60,3913', Decimal('1234.50')),
            ('en', '1234.5', '60.3913', Decimal('1234.50')), ('tr', '1234.5', '60.3913', Decimal('1234.50')),
        ]:
            with self.subTest(language=language, area=area):
                Site.all_objects.all().delete()
                self.in_language(language)
                self.client.post(reverse('farm:site_create'),
                                 site_data(area_m2=area, latitude=latitude, longitude='5,3221' if ',' in latitude else '5.3221'))
                site = Site.objects.get()
                self.assertEqual((site.area_m2, site.latitude), (expected, Decimal('60.391300')))

    def test_dates_follow_the_language(self):
        entry_time = datetime(2026, 11, 2, 13, 5, tzinfo=utc.utc)
        with mock.patch('django.utils.timezone.now', return_value=entry_time):
            AuditLog.objects.create(user=self.user, user_name='ali', action='create', entity_type='site',
                                    entity_id='1', entity_label='Bergen (BG)')
        for language, shown in [('en', '2 Nov 2026, 13:05'), ('tr', '02 Kasım 2026 13:05'),
                                ('nb', '2. november 2026 13:05')]:
            self.in_language(language)
            self.assertContains(self.client.get(reverse('core:activity_log')), shown, msg_prefix=language)


class ActivityLogLanguageTests(TestCase):
    """The log is English at rest whatever language the change was made in, and shown in the language of
    whoever reads it."""

    def setUp(self):
        self.user = get_user_model().objects.create_user('ali', 'ali@example.com', 'x')
        self.user.groups.add(role('Site manager', *SITE_MANAGER))
        self.client.force_login(self.user)

    def in_language(self, language):
        Profile.objects.update_or_create(user=self.user, defaults={'language': language})

    def test_rows_are_stored_in_english_whatever_the_language_of_the_change(self):
        self.in_language('tr')
        self.client.post(reverse('farm:site_create'), site_data(name='Pond', code='bg', status='maintenance',
                                                               type='hatchery'))
        site = Site.objects.get()
        self.in_language('nb')
        self.client.post(reverse('farm:site_edit', args=[site.pk]),
                         site_data(name='Pond', code='bg', status='closed', type='hatchery', version='1'))
        self.in_language('tr')
        self.client.post(reverse('farm:site_contacts', args=[site.pk]),
                         contacts_data([{'name': 'Kari', 'role': 'Vet', 'is_primary': True}], record=site))
        created, edited, contacts = AuditLog.objects.order_by('created_at')
        self.assertEqual((created.action, created.entity_type), ('create', 'site'))
        self.assertEqual(created.changes['Site name'], [None, 'Pond'])
        self.assertEqual(created.changes['Status'], [None, message('Under maintenance')])
        self.assertEqual(created.changes['Site type'], [None, message('Hatchery')])
        self.assertEqual(edited.changes, {'Status': [message('Under maintenance'), message('Closed')]})
        self.assertEqual(contacts.changes, {'Contacts': [None, 'Kari (Vet, primary)']})

    def test_the_page_shows_them_in_the_readers_language_but_not_a_persons_own_text(self):
        self.in_language('en')
        self.client.post(reverse('farm:site_create'), site_data(name='Pond', code='bg', status='maintenance',
                                                               type='hatchery'))
        site = Site.objects.get()
        for language, words in {
            'en': ['Created', 'Site name', 'Under maintenance', 'Hatchery', 'Site ·'],
            'tr': ['Oluşturuldu', 'Saha adı', 'Bakımda', 'Kuluçkahane', 'Saha ·'],
            'nb': ['Opprettet', 'Lokalitetsnavn', 'Under vedlikehold', 'Klekkeri', 'Lokalitet ·'],
        }.items():
            self.in_language(language)
            for url in (reverse('core:activity_log'), reverse('farm:site_edit', args=[site.pk])):
                page = self.client.get(url)
                for word in words:
                    if word.endswith('·') and 'activity' not in url:
                        continue                  # the History tab does not repeat the record type
                    self.assertContains(page, word, msg_prefix=f'{language} {url}')
                self.assertContains(page, '<dd>Pond</dd>')      # a site called Pond is not the pond type
                self.assertNotContains(page, 'msgid')

    def test_the_filters_name_record_types_in_the_readers_language(self):
        self.client.post(reverse('farm:site_create'), site_data())
        self.in_language('nb')
        page = self.client.get(reverse('core:activity_log'))
        self.assertContains(page, '<option value="site">Lokalitet</option>', html=True)
        self.assertContains(page, '<option value="create">Opprettet</option>', html=True)

    def test_a_records_name_is_stored_in_english_whatever_the_language(self):
        from django.utils import translation

        from core import audit
        from farm.models import WaterLimit
        from farm.tests.helpers import make_species
        limit = WaterLimit.objects.create(species=make_species(), parameter='temperature_c', critical_high=20)
        with translation.override('en'):
            english = str(limit)
        with translation.override('nb'):
            self.assertNotEqual(str(limit), english)          # the name has translated words in it
            row = audit.record(self.user, AuditLog.Action.CREATE, limit)
        self.assertEqual(row.entity_label, english)

    def test_deleting_in_a_language_still_logs_in_english(self):
        site = Site.objects.create(name='Bergen', code='BG')
        ProductionDepartment.objects.create(name='Hall A', code='HA', site=site)
        self.user.groups.add(role('Production department manager', 'view_productiondepartment'))
        self.in_language('tr')
        self.client.post(reverse('farm:site_delete', args=[site.pk]))
        rows = {row.entity_type: row for row in AuditLog.objects.all()}
        self.assertEqual(set(rows), {'site', 'production department'})
        self.assertEqual(rows['production department'].changes, {'Site': ['Bergen (BG)', None]})

    def test_role_permissions_are_logged_in_english_too(self):
        admin = get_user_model().objects.create_superuser('root', 'root@example.com', 'x')
        Profile.objects.create(user=admin, language='tr')
        self.client.force_login(admin)
        self.client.post(reverse('core:group_create'), {'name': 'Feeder', 'permissions': perms('farm.view_site')})
        self.assertEqual(AuditLog.objects.get().changes,
                         {'Role name': [None, 'Feeder'], 'Permissions': [None, 'Sites: read']})


class EmailLanguageTests(TestCase):
    """An email is written in the recipient's language where it is known."""

    def test_the_reset_email_uses_the_saved_language_of_the_recipient(self):
        user = get_user_model().objects.create_user('kari', 'kari@example.com', 'x')
        Profile.objects.create(user=user, language='tr')
        self.client.post(reverse('password_reset'), {'email': 'kari@example.com'}, headers={'Accept-Language': 'nb'})
        sent = mail.outbox[0]
        self.assertEqual(sent.subject, 'Parolanızı sıfırlayın')
        self.assertIn('Merhaba kari,', sent.body)
        self.assertIn('Yeni parola belirlemek için bu bağlantıyı açın:', sent.body)

    def test_without_a_saved_language_the_email_follows_the_language_it_was_asked_in(self):
        get_user_model().objects.create_user('kari', 'kari@example.com', 'x')
        self.client.post(reverse('password_reset'), {'email': 'kari@example.com'}, headers={'Accept-Language': 'nb'})
        self.assertEqual(mail.outbox[0].subject, 'Tilbakestill passordet ditt')
        self.client.cookies[COOKIE] = 'en'
        self.client.post(reverse('password_reset'), {'email': 'kari@example.com'})
        self.assertEqual(mail.outbox[1].subject, 'Reset your password')

    def test_an_invitation_is_written_in_the_language_the_admin_chose_for_the_new_person(self):
        admin = get_user_model().objects.create_superuser('root', 'root@example.com', 'x')
        self.client.force_login(admin)                                  # the admin reads English
        self.client.post(reverse('core:user_create'), user_data(language='nb'))
        self.assertEqual(Profile.objects.get(user__username='kari').language, 'nb')
        self.assertEqual(mail.outbox[0].subject, 'Tilbakestill passordet ditt')
        self.assertIn('Hei kari,', mail.outbox[0].body)
        self.assertEqual(lang_of(self.client.get(reverse('home'))), 'en')     # the admin's own page is unchanged


class UserLanguageFieldTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser('root', 'root@example.com', 'x')
        self.client.force_login(self.admin)

    def test_the_users_language_is_chosen_on_the_user_form_and_logged(self):
        self.client.post(reverse('core:user_create'), user_data(language='tr'))
        kari = get_user_model().objects.get(username='kari')
        self.assertEqual(kari.profile.language, 'tr')
        form = self.client.get(reverse('core:user_edit', args=[kari.pk])).context['form']
        self.assertEqual(form['language'].value(), 'tr')
        self.client.post(reverse('core:user_edit', args=[kari.pk]), user_data(language='nb'))
        kari.refresh_from_db()
        self.assertEqual(Profile.objects.get(user=kari).language, 'nb')
        created, edited = AuditLog.objects.order_by('created_at')
        self.assertEqual(created.changes['Language'], [None, 'Türkçe'])
        self.assertEqual(edited.changes, {'Language': ['Türkçe', 'Norsk bokmål']})

    def test_a_language_that_is_not_offered_is_refused_and_empty_means_the_browsers(self):
        response = self.client.post(reverse('core:user_create'), user_data(language='de'))
        self.assertIn('language', response.context['form'].errors)
        self.assertFalse(get_user_model().objects.filter(username='kari').exists())
        self.client.post(reverse('core:user_create'), user_data(language=''))
        self.assertEqual(Profile.objects.get(user__username='kari').language, '')
        self.assertEqual(AuditLog.objects.get().changes.get('Language'), None)
