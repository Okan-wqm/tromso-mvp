"""The Suderra Platform shell (docs/design/system): the theme a person picks (Fjord, Polarnatt, Nordlys, Tang, Laks) is a cookie that sets
data-theme on <html>, never the system's colour scheme; the two typefaces are served from this server; the rail carries
the logo disc and the wordmark; below 1024 px a bottom bar holds the daily pages and More, which opens the whole menu."""
import re
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from farm.tests.helpers import role

from . import theme

ROOT = Path(settings.BASE_DIR)


def html_tag(response):
    return re.search(r'<html[^>]*>', response.content.decode()).group(0)


class ThemeCookieTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser('root', 'root@example.com', 'x')
        self.client.force_login(self.admin)

    def test_fjord_is_the_default(self):
        self.assertIn('data-theme="fjord"', html_tag(self.client.get(reverse('home'))))

    def test_choosing_a_theme_sets_the_cookie_and_returns_to_the_page(self):
        response = self.client.post(reverse('core:set_theme'), {'theme': 'polarnatt',
                                                                 'next': reverse('farm:site_list')})
        self.assertRedirects(response, reverse('farm:site_list'), fetch_redirect_response=False)
        cookie = response.cookies[theme.COOKIE]
        self.assertEqual(cookie.value, 'polarnatt')
        self.assertEqual(cookie['samesite'], 'Lax')
        self.assertGreaterEqual(int(cookie['max-age']), 365 * 24 * 3600)
        self.assertIn('data-theme="polarnatt"', html_tag(self.client.get(reverse('home'))))

    def test_every_theme_of_the_design_system_is_offered(self):
        for value in ('fjord', 'polarnatt', 'nordlys', 'tang', 'laks'):
            with self.subTest(theme=value):
                self.client.post(reverse('core:set_theme'), {'theme': value, 'next': '/'})
                self.assertIn(f'data-theme="{value}"', html_tag(self.client.get(reverse('home'))))

    def test_the_old_day_and_night_are_not_themes(self):
        for value in ('light', 'dark'):
            with self.subTest(theme=value):
                response = self.client.post(reverse('core:set_theme'), {'theme': value, 'next': '/'})
                self.assertNotIn(theme.COOKIE, response.cookies)

    def test_an_unknown_theme_changes_nothing(self):
        self.client.post(reverse('core:set_theme'), {'theme': 'tang', 'next': '/'})
        response = self.client.post(reverse('core:set_theme'), {'theme': 'pink', 'next': '/'})
        self.assertNotIn(theme.COOKIE, response.cookies)
        self.assertIn('data-theme="tang"', html_tag(self.client.get(reverse('home'))))

    def test_a_forged_cookie_falls_back_to_fjord(self):
        self.client.cookies[theme.COOKIE] = '"><script>'
        self.assertIn('data-theme="fjord"', html_tag(self.client.get(reverse('home'))))

    def test_it_never_sends_the_person_to_another_site(self):
        response = self.client.post(reverse('core:set_theme'), {'theme': 'laks', 'next': 'https://evil.example/'})
        self.assertRedirects(response, '/', fetch_redirect_response=False)

    def test_only_a_post_changes_it(self):
        self.assertEqual(self.client.get(reverse('core:set_theme'), {'theme': 'laks'}).status_code, 405)

    def test_the_sign_in_page_follows_the_cookie(self):
        self.client.logout()
        self.client.cookies[theme.COOKIE] = 'nordlys'
        self.assertIn('data-theme="nordlys"', html_tag(self.client.get(reverse('login'))))

    def test_the_user_menu_offers_the_five_themes_beside_the_language(self):
        self.client.post(reverse('core:set_theme'), {'theme': 'laks', 'next': '/'})
        html = self.client.get(reverse('home')).content.decode()
        menu = html[html.index('id="user-panel"'):]
        menu = menu[:menu.index('</form>', menu.index('name="theme"'))]
        self.assertIn('menu-language', menu)
        buttons = re.findall(r'<button[^>]*name="theme"[^>]*>', menu)
        self.assertEqual([re.search(r'value="(\w+)"', button).group(1) for button in buttons], ['fjord', 'polarnatt', 'nordlys', 'tang', 'laks'])
        self.assertEqual([('aria-pressed="true"' in button) for button in buttons], [False, False, False, False, True])


class ThemeIsNeverTheSystemsTests(SimpleTestCase):
    def test_no_stylesheet_or_script_reads_the_systems_colour_scheme(self):
        for path in [*(ROOT / 'static' / 'css').glob('*.css'), *(ROOT / 'frontend').rglob('*.ts')]:
            with self.subTest(path=path.name):
                self.assertNotIn('prefers-color-scheme', path.read_text(encoding='utf-8'))


class SelfHostedFontsTests(SimpleTestCase):
    def test_no_page_asks_another_server_for_a_font(self):
        for path in (ROOT / 'templates').rglob('*.html'):
            text = path.read_text(encoding='utf-8')
            with self.subTest(template=path.name):
                self.assertNotIn('fonts.googleapis', text)
                self.assertNotIn('fonts.gstatic', text)
        for path in (ROOT / 'static' / 'css').glob('*.css'):
            with self.subTest(stylesheet=path.name):
                self.assertNotRegex(path.read_text(encoding='utf-8'), r'@import|url\(["\']?https?:')

    def test_every_font_the_stylesheet_names_is_served_here_with_its_licence(self):
        fonts = (ROOT / 'static' / 'css' / 'fonts.css').read_text(encoding='utf-8')
        files = re.findall(r'url\("\.\./fonts/([^"]+)"\)', fonts)
        self.assertEqual(len(files), 4)
        for name in files:
            self.assertTrue((ROOT / 'static' / 'fonts' / name).is_file(), name)
        for licence in ('OFL-atkinson-hyperlegible-next.txt', 'OFL-bricolage-grotesque.txt'):
            self.assertIn('SIL Open Font License', (ROOT / 'static' / 'fonts' / licence).read_text(encoding='utf-8'))
        third_party = (ROOT / 'THIRD_PARTY.md').read_text(encoding='utf-8')
        self.assertIn('Atkinson Hyperlegible Next', third_party)
        self.assertIn('Bricolage Grotesque', third_party)


class TokenSourceTests(SimpleTestCase):
    """One source for the tokens: the design system's `docs/design/system/tokens.css` (made from its tokens.json, the
    hand-off's own file, which its previews load). The stylesheet the pages load, `static/css/tokens.css`, is that file
    unchanged with the app's own block after it, so a colour or a size changed in one and not in the other fails here
    instead of drifting unseen."""
    APP = '/* App additions (not in tokens.json yet)'

    def test_the_apps_tokens_are_the_design_systems_with_the_apps_own_block_after_them(self):
        def read(path):
            return path.read_text(encoding='utf-8').replace(chr(13), '')
        system = read(ROOT / 'docs' / 'design' / 'system' / 'tokens.css')
        served = read(ROOT / 'static' / 'css' / 'tokens.css')
        self.assertTrue(served.startswith(system), 'static/css/tokens.css no longer starts with docs/design/system/'
                        'tokens.css: change the design system’s file and copy it, never one of the two')
        own = served[len(system):]
        self.assertTrue(own.strip().startswith(self.APP))
        blocks = re.findall(r'([^{}]+)\{([^{}]*)\}', re.sub(r'/\*.*?\*/', '', own, flags=re.S))
        self.assertEqual([selector.strip() for selector, _body in blocks], [':root'])       # one block, no theme's
        names = re.findall(r'(--[a-z0-9-]+)\s*:', blocks[0][1])
        self.assertEqual(sorted(names), sorted(set(names)))
        # the app's block adds names; it never sets one the design system sets (that would be a second source)
        self.assertEqual(set(names) & set(re.findall(r'(--[a-z0-9-]+)\s*:', system)), set())


class ColourLiteralTests(SimpleTestCase):
    def test_no_colour_is_written_outside_the_tokens(self):
        literal = re.compile(r'#[0-9A-Fa-f]{3,8}\b|rgba?\(')
        for path in (ROOT / 'static' / 'css').glob('*.css'):
            if path.name == 'tokens.css':
                continue
            with self.subTest(stylesheet=path.name):
                # an @supports condition only asks the browser what it can parse (tw.css's `color:rgb(from red r g b)`
                # finds the browsers without @property): it paints nothing
                hits = [line for line in path.read_text(encoding='utf-8').splitlines()
                        if not line.lstrip().startswith('@supports')
                        and literal.search(re.sub(r'url\([^)]*\)', '', line))]
                self.assertEqual(hits, [])


class RailTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser('root', 'root@example.com', 'x')
        self.client.force_login(self.admin)

    def test_the_rail_carries_the_logo_disc_and_the_two_tone_wordmark(self):
        html = self.client.get(reverse('farm:meal_board')).content.decode()
        self.assertRegex(html, r'<img class="ui-logo" src="/static/img/suderra-mark-disc\.png\?v=\d+" alt="">')
        self.assertIn('<span class="ui-wordmark">SU<span>DERRA</span></span>', html)

    def test_the_language_switch_sits_in_the_top_bar(self):
        html = self.client.get(reverse('farm:meal_board')).content.decode()
        topbar = html[html.index('<header class="topbar'):html.index('id="user-panel"')]
        self.assertIn('class="language-switch', topbar)


class BottomBarTests(TestCase):
    """Below 1024 px the rail gives way to a bottom bar (README, Shell): Meals, Water, Units, Storage and More."""

    def setUp(self):
        self.admin = get_user_model().objects.create_superuser('root', 'root@example.com', 'x')

    def bar(self, response):
        html = response.content.decode()
        start = html.index('<nav class="ui-bottombar"')
        return html[start:html.index('</nav>', start)]

    def test_production_puts_the_daily_pages_in_it_then_more(self):
        self.client.force_login(self.admin)
        bar = self.bar(self.client.get(reverse('farm:meal_board')))
        links = re.findall(r'<a class="ui-bottombar-link" href="([^"]+)"([^>]*)>', bar)
        self.assertEqual([href for href, _ in links], [reverse('farm:meal_board'), reverse('farm:water'),
                                                      reverse('farm:production_units'), reverse('inventory:storage')])
        self.assertIn('aria-current="page"', links[0][1])
        self.assertNotIn('aria-current', links[1][1])
        self.assertRegex(bar, r'<button type="button" class="ui-bottombar-link" data-nav-open aria-controls="rail" '
                              r'aria-expanded="false">')
        self.assertEqual(re.findall(r'class="ui-bottombar-label">([^<]+)<', bar),
                         ['Meals', 'Water', 'Units', 'Storage', 'More'])

    def test_a_person_sees_only_the_pages_their_role_opens(self):
        user = get_user_model().objects.create_user('ali', 'ali@example.com', 'x')
        user.groups.add(role('Water only', 'view_watermeasurement'))
        self.client.force_login(user)
        bar = self.bar(self.client.get(reverse('farm:water')))
        self.assertEqual(re.findall(r'class="ui-bottombar-label">([^<]+)<', bar), ['Water', 'More'])

    def test_the_company_panel_takes_its_first_pages(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('home'))
        bar = self.bar(response)
        first = [entry['url'] for section in response.context['rail_sections'] for group in section['groups']
                 for entry in group['entries']][:4]
        self.assertEqual(re.findall(r'<a class="ui-bottombar-link" href="([^"]+)"', bar), first)


class RailOrderTests(TestCase):
    """The rail in daily order (docs/design/system/README.md, Shell): the day's work first, Setup collapsed and last,
    open on its own pages; the foot says the company and the person's site."""

    def setUp(self):
        self.admin = get_user_model().objects.create_superuser('root', 'root@example.com', 'x')
        self.client.force_login(self.admin)

    def rail(self, url):
        html = self.client.get(url).content.decode()
        return html[html.index('id="rail"'):html.index('</aside>')]

    def test_setup_comes_last_in_production_and_in_sensors(self):
        for url in (reverse('farm:meal_board'), reverse('sensors:home')):
            with self.subTest(url=url):
                sections = [section['label'] for section in self.client.get(url).context['rail_sections']]
                self.assertEqual(sections[-1], 'Setup')
                self.assertEqual(sections[0], '')

    def test_setup_is_folded_away_on_a_days_page_and_open_on_its_own(self):
        closed = self.rail(reverse('farm:meal_board'))
        self.assertRegex(closed, r'<details class="rail-collapse" data-collapse="production-setup">\s*'
                                 r'<summary class="rail-section">Setup</summary>')
        opened = self.rail(reverse('farm:system_list'))
        self.assertRegex(opened, r'<details class="rail-collapse" data-collapse="production-setup" open data-current>')

    def test_the_foot_says_the_company_and_the_persons_site(self):
        from farm.models import ProductionDepartment, Site
        from hr.tests.helpers_people import employee, place
        site = Site.objects.create(name='Bergen Hatchery', code='BH-01', timezone='Europe/Oslo')
        Site.objects.create(name='Tromsø Grow-out', code='TG-02', timezone='Europe/Oslo')
        department = ProductionDepartment.objects.create(name='Hatchery hall A', code='HA', site=site)
        with self.settings(COMPANY_NAME='Nordhav Akva'):
            self.assertIn('<div class="rail-foot">Nordhav Akva</div>', self.rail(reverse('home')))
            place(employee('E-1', last='', first='', user=self.admin), department)      # (the name is the account's)
            self.assertIn('<div class="rail-foot">Nordhav Akva · Bergen Hatchery</div>', self.rail(reverse('home')))

    def test_one_site_is_the_sites_and_without_a_company_name_the_site_alone(self):
        from farm.models import Site
        Site.objects.create(name='Bergen Hatchery', code='BH-01', timezone='Europe/Oslo')
        with self.settings(COMPANY_NAME=''):
            self.assertIn('<div class="rail-foot">Bergen Hatchery</div>', self.rail(reverse('home')))


class DisplayWeightTests(SimpleTestCase):
    """Bricolage Grotesque is served at 600 only (static/css/fonts.css): a rule that sets it, or a heading it draws (h1,
    h2), asks for no other weight, so the browser never fakes a bold."""

    def test_the_display_face_is_never_asked_for_another_weight(self):
        rule = re.compile(r'([^{}]+)\{([^{}]*)\}')
        found = []
        for path in (ROOT / 'static' / 'css').glob('*.css'):
            css = re.sub(r'/\*.*?\*/', '', path.read_text(encoding='utf-8'), flags=re.S)
            for selectors, body in rule.findall(css):
                display = 'var(--font-display)' in body or 'Bricolage' in body or any(
                    re.search(r'(^|[\s>+~,])h[12]\b', selector.strip()) for selector in selectors.split(','))
                weight = re.search(r'font-weight:\s*(\d+)', body)
                if display and weight and weight.group(1) != '600':
                    found.append(f'{path.name}: {selectors.strip()} {weight.group(1)}')
        self.assertEqual(found, [])

    def test_the_sign_in_wordmark_is_set_in_the_display_face(self):
        css = (ROOT / 'static' / 'css' / 'auth.css').read_text(encoding='utf-8')
        brand = re.search(r'\n\.brand \{([^}]*)\}', css).group(1)
        self.assertIn('var(--font-display)', brand)
