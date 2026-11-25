"""The real templates the browser layout test lays out (frontend/test/layout.browser.test.ts): each part rendered by Django
from fixed, made-up records (no database), written to frontend/test/pages/<name>.html and committed, so the browser test
reads what the templates print, not markup written by hand. `manage.py layout_pages` writes them again; its `--check` (and
core/tests_layout_pages.py) fails when a template changed and the parts were not written again."""
from datetime import date, datetime, timezone as tz
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace as N
from unittest import mock

from django.conf import settings
from django.template.loader import render_to_string
from django.utils import translation

FOLDER = Path(settings.BASE_DIR, 'frontend', 'test', 'pages')
NOW = datetime(2026, 11, 6, 9, 19, tzinfo=tz.utc)


class _Named(N):
    """A made-up record that prints as its `text`."""
    def __str__(self):
        return self.text


def _stock():
    site = N(pk=1, name='Bergen Hatchery')
    location = N(pk=2, code='RES-FR', name='Research hall feed room')
    item = _Named(pk=3, text='Trial diet EPA+DHA 1.0 % 3 mm (TD-EPA10)', get_unit_display=lambda: 'kg')
    lot = _Named(text='FF-26-4410', expiry_date=date(2027, 4, 20))
    bucket = N(location=location, site=site, item=item, lot=lot, quantity=Decimal('144.476'),
               last_movement=date(2026, 10, 31), value=Decimal('5490.09'), cost=(None, 'NOK'))
    rows = [{'bucket': bucket, 'item_url': '#', 'lot_url': '#', 'expired': False,
             'actions': [('#', 'Transfer'), ('#', 'Issue'), ('#', 'Write off'), ('#', 'Return')]}]
    return render_to_string('inventory/_stock.html', {
        'sites': [site], 'locations': [N(pk=2, code='RES-FR', name='Research hall feed room, the long name of a room')],
        'items': [_Named(pk=3, text='Trial diet EPA+DHA 1.0 % 3 mm (TD-EPA10), a feed with a long name')],
        'params': {}, 'rows': rows, 'totals': []})


def _readings(language):
    """Real water readings (farm.water.read) of a unit's middle point, three of them from sensors."""
    from farm.models import ProductionDepartment, SamplingPoint, Site, Tank
    from farm.water import parameters
    from farm.water.evaluate import Status
    from farm.water.read import Observation, Origin, Reading

    site = Site(name='Bergen Hatchery', code='BG', timezone='Europe/Oslo')
    unit = Tank(code='HA-K03', name='Fry tank 3', production_department=ProductionDepartment(name='Hall A', site=site))
    point = SamplingPoint(unit=unit, name='Middle', kind='middle')
    readings = {}
    for code, value, channel in (('oxygen_saturation_pct', '98.6', 19), ('co2_mg_l', '11.5', 221), ('ph', '7.41', 20),
                                 ('temperature_c', '13.6', 17)):
        origin = Origin.SYSTEM_SENSOR if channel > 200 else Origin.SENSOR
        observation = Observation(point, NOW, origin, {code: Decimal(value)}, channel_no=channel, fresh_for=180)
        readings[code] = Reading(parameters.get(code), Decimal(value), observation, status=Status.OK)
    return point, readings


def _water():
    point, readings = _readings('en')
    cells = ''.join(render_to_string('farm/_water_cell.html', {'reading': reading, 'latest': True, 'source': True,
                                                                'at': NOW})
                    for reading in readings.values())
    return (f'<div class="table-wrap"><table class="data-table water-table"><tbody><tr><th scope="row">{point.unit.code}'
            f'</th>{cells}</tr></tbody></table></div>')


def _card(language):
    with translation.override(language):
        point, readings = _readings(language)
        body = render_to_string('monitoring/widgets/_water_point.html', {
            'water': N(point=point, readings=readings), 'named': False, 'card': N(now=NOW),
            'view': N(opts={'points': 'middle', 'parameters': 'all'})})
    return f'<article class="monitor-card monitor-ok" lang="{language}" style="width: 21rem">{body}</article>'


def _matrix():
    def cell(index):
        return {'name': 'permissions', 'type': 'checkbox', 'value': str(index), 'attrs': {'id': f'id_p_{index}'},
                'template_name': 'django/forms/widgets/checkbox.html'}
    columns = ['Read', 'Create', 'Edit', 'Delete', 'Crew', 'All production', 'Everyone']
    rows = [{'label': label, 'cells': [(column, cell(n * 10 + i)) for i, column in enumerate(columns)], 'notes': []}
            for n, label in enumerate(['Shift schedule', 'Leave requests', 'Attendance', 'Employees'])]
    return render_to_string('core/widgets/permission_matrix.html', {'widget': {
        'attrs': {'id': 'matrix'}, 'columns': columns, 'sections': [('Company · HR', rows)]}})


def _approve():
    leave = N(pk='00247833-d3b1-4ae0-b20b-56345ecb0083', first_day=date(2026, 11, 9), last_day=date(2026, 11, 13),
              employee=N(full_name='Jonas Eide'))
    return render_to_string('hr/leave_approve.html', {'object': leave, 'impact': [], 'base_template': 'modal_base.html',
                                                      'request': None,
                                                      'title': 'Approve leave', 'group': 'Production · Team'})


def _tabs():
    """Norwegian's long tab names, as many as a page has."""
    with translation.override('nb'):
        return render_to_string('farm/_harvest_tabs.html', {'tabs': [
            {'url': '#', 'label': label, 'current': index == 0} for index, label in enumerate(
                ('Høstet', 'Høsteplan', 'Produksjonsplaner', 'Slakteriene', 'Håndteringsregler', 'Behandlinger'))]})


def _report_tabs():
    """The Reports page's strip of kinds as the page prints it for /reports/?kind=smolt (reports.resources._tabs): twelve
    link tabs and the two group names, the current one a scheduled kind (Smolt), with the counts of the
    reports due that a long strip carries."""
    from reports.kinds import ReportKind
    from reports.resources import _tabs

    due = [N(kind=ReportKind.SMOLT.value)] * 3 + [N(kind=ReportKind.BIOMASS.value)] + [N(kind=ReportKind.DISEASE.value)]
    return render_to_string('reports/_report_tabs.html', {'tabs': _tabs(N(GET={}), due, ReportKind.SMOLT.value)})


def _meal():
    """The meal board's table with the seeded farm's longest lines: a trial's placement chip, an estimate to weigh
    soon and an incomplete one, a temperature read through a loop and stale, a line whose ration cannot be worked out."""
    department = N(name='Hatchery hall A', site=N(name='Bergen Hatchery'))
    feed = N(code='SGR-3', pellet_size_mm=Decimal('3'))
    band = N(min_weight_g=Decimal('0'), max_weight_g=Decimal('100'), feed=feed)
    sfr = N(value=Decimal('1.56'), interpolated=False)

    def basis(protocol='Salmon smolt RAS, standard', missing=''):
        return N(protocol=N(name=protocol), scope='batch', band=band, fcr=Decimal('1.00'), sfr=sfr, missing=missing)

    def share(next_kg, fish=15830, blind=0, end=None):
        return N(fish=fish, biomass_kg=Decimal('1048.3'), end_g=Decimal('66.2'), measured_g=Decimal('66.0'),
                 last_weighed=date(2026, 11, 3), blind_days=blind, next_meal_kg=next_kg,
                 remaining_kg=None if next_kg is None else next_kg * 4, over_kg=Decimal('0'),
                 ration_kg=None if next_kg is None else next_kg * 4, planned_meals=4, meal_kg=next_kg, meals=0,
                 end=end or basis())

    def line(batch, part, why='', drift=''):
        return {'share': part, 'batch': N(code=batch), 'why': why, 'drift': drift, 'estimate_days': 16}

    from farm.feeding.temperature import Temperature    # the board's own: its stale chip says A11's age warning
    measured = datetime(2026, 11, 5, 20, 0, tzinfo=tz.utc)
    temperature = Temperature(value_c=Decimal('11.6'), measured_at=measured, point=N(code='RAS-1', site=None),
                              via='loop', age=NOW - measured, fresh=False)
    day = N(fed_kg=Decimal('0'), feedings=[], meals_done=0)
    rows = [
        {'unit': N(code='HA-K02', production_department=department), 'day': day, 'temperature': temperature,
         'placements': [], 'record_url': '#', 'water_url': '#',
         'lines': [line('B-2026-001', share(Decimal('0.761'), fish=3000, blind=1), drift='soon')]},
        {'unit': N(code='HA-K03', production_department=department), 'day': day, 'temperature': temperature,
         'placements': [], 'record_url': '#', 'water_url': '#',
         'lines': [line('B-2026-001', share(None, fish=1000, end=basis(missing='outside_table')),
                        why='13.1 °C is outside this table (8.0–12.0 °C).')]},
        {'unit': N(code='RT-01', production_department=N(name='Research hall', site=N(name='Bergen Hatchery'))),
         'day': day, 'temperature': temperature, 'record_url': '#', 'water_url': '#',
         'placements': [N(url='#', title='Experiment E-2026-002', label='E-2026-002 · EPA+DHA 1.0 %, low density · R1')],
         'lines': [line('B-2026-003', share(Decimal('0.025'), fish=100,
                                            end=basis('R&D diet trial – EPA+DHA 1.0 %, low density')))]},
    ]
    return render_to_string('farm/_meal_board_table.html', {'rows': rows})


def _overview():
    """Production › Overview's body (templates/_production_overview.html) with every part a full right shows: two critical
    water points and a warning (real readings with their origin and age), overdue tasks and an overdue report with a long
    name, the day's ten metric cards, the reports due and the farm's structure with every system status and unit kind, in
    Norwegian (its labels are the longest)."""
    from django.utils.translation import gettext as _
    from farm.water.evaluate import Status

    with translation.override('nb'):
        point, readings = _readings('nb')
        outlet = N(name='Østre sideutløp ved bunnen')
        alerts = []
        for status, where, codes in ((Status.CRITICAL, outlet, ('co2_mg_l', 'ph')),
                                     (Status.CRITICAL, point, ('temperature_c',)),
                                     (Status.WARNING, point, ('oxygen_saturation_pct',))):
            found = [(readings[code], status, False) for code in codes]
            alerts.append({'point': where, 'owner': point.unit, 'loop': False, 'history_url': '#',
                           'water': N(point_status=status, old_alert=False, alerts=found)})
        kind = N(label='Planlagt slakting')
        upcoming = {'late': [N(kind=kind, place='Fjord Seafood Processing (N1234)', period=N(label='Uke 45 av 2026'),
                               deadline=date(2026, 10, 29), overdue=True)],
                    'due': [N(kind=N(label='Sykdom'), place='Tromsø Grow-out (TG-02)', period=None, deadline=None,
                              overdue=False)],
                    'late_duties': [], 'due_duties': [], 'more': 2, 'count': 4, 'url': '#', 'duties_url': '#',
                    'at_once': [], 'not_set_up': []}
        return render_to_string('_production_overview.html', {
            'now': NOW, 'late_tasks': 18, 'late_reports': 1,
            'stock': {'stocked': {'label': _('Stocked units'), 'count': 19, 'of': 23, 'url': '#'},
                      'fish': {'label': _('Fish'), 'count': '311\xa0665', 'url': '#'},
                      'biomass': {'label': _('Biomass'), 'count': '137,9\xa0t', 'url': '#'}},
            'feeding': {'today': {'label': _('Feed today'), 'count': '848\xa0kg', 'url': '#'},
                        'week': {'label': _('Feed, last 7 days'), 'count': '7,4\xa0t', 'url': '#'}},
            'tasks': {'due_today': {'label': _('Tasks due today'), 'count': 3, 'url': '#'},
                      'overdue': {'label': _('Overdue tasks'), 'count': 18, 'url': '#'}},
            'water': {'points': 40, 'critical': 2, 'warning': 6, 'alerts': alerts, 'more': 4, 'url': '#',
                      'sensors_failed': False, 'unmeasured': [], 'window_days': 30},
            'at_once': 0, 'not_set_up': 0, 'unmeasured': 0,
            'upcoming': upcoming,
            'tiles': [{'key': 'productiondepartment', 'label': _('Production departments'), 'count': 6, 'url': '#'},
                      {'key': 'system', 'label': _('Systems'), 'count': 6, 'url': '#'},
                      {'key': 'equipment', 'label': _('Equipment'), 'count': 29, 'url': '#'},
                      {'key': 'tank', 'label': _('Tanks, ponds & cages'), 'count': 23, 'url': '#'}],
            'systems_by_status': [{'value': value, 'label': _(label), 'count': count, 'url': '#'} for value, label, count in
                                  (('operational', 'Operational', 5), ('maintenance', 'Maintenance', 1),
                                   ('offline', 'Offline', 0), ('construction', 'Construction', 0))],
            'units_by_kind': [{'value': value, 'label': _(label), 'count': count, 'url': '#'}
                              for value, label, count in (('tank', 'Tank', 19), ('pond', 'Pond', 0), ('cage', 'Cage', 4))],
        })


# The units of the wall part: (code, name, oxygen mg/L, its status, temperature, pH, alkalinity, TAN, hours since the
# sensors answered, what else). Twenty, in every state a Small card can be in.
_WALL = (
    [('HA-K01', 'Smolt tank 1', '10.30', 'ok', '13.1', '7.21', '112', '0.61', 0.01, 'withdrawal'),
     ('HA-K02', 'Start tank 2', '6.40', 'warning', '13.1', '7.05', '104', '0.58', 0.01, ''),
     ('HA-K03', 'Fry tank 3', '10.30', 'ok', '13.1', '7.40', '118', '0.42', 0.01, ''),
     ('HA-R01', 'Raceway 1', '9.90', 'ok', '11.5', '7.30', '122', '0.47', 0.01, ''),
     ('HA-R02', 'D-end raceway 2 with a long name', '5.10', 'critical', '11.5', '6.62', '122', '0.61', 0.01, 'second')]
    + [(f'RT-{number:02d}', f'Trial tank {number}', f'9.{30 + number}', 'ok', '9.2', f'7.{20 + number % 9}', '96',
        '0.35', 0.01, '') for number in range(1, 8)]
    + [('RT-08', 'Trial tank 8', '9.38', 'stale', '9.2', '7.17', '96', '0.35', 96, ''),
       ('RT-09', 'Trial tank 9', '9.33', 'ok', '9.3', '7.25', '96', '0.35', 0.01, 'maintenance'),
       ('RT-10', 'Trial tank 10', '9.47', 'ok', '9.4', '7.26', '96', '0.35', 0.01, ''),
       ('RT-11', 'Trial tank 11', '9.02', 'ok', '9.2', '8.31', '96', '0.90', 0.01, ''),
       ('RT-12', 'Trial tank 12', '9.41', 'ok', '9.2', '7.23', '96', '0.35', 0.01, 'empty'),
       ('TG-M01', 'Cage M1', '9.80', 'ok', '8.4', '7.98', '', '0.10', 0.01, ''),
       ('TG-M03', 'Cage M3', '9.90', 'ok', '8.3', '8.02', '110', '0.10', 0.01, 'sea'),
       ('TG-M04', 'Cage M4', '9.90', 'ok', '8.3', '8.02', '110', '0.10', 0.01, '')])


def _wall(language, pane='', cards_only=False):
    """A wall of twenty Small cards with its band (monitoring/_grid.html), from made-up units and readings and the REAL
    chart of each (the chemistry core through calculation.charts_of, the fish's limits made up too): a normal card, a
    warning, a critical one with a second reason, old values, a unit not in use, a withdrawal, an empty unit, a chart
    that cannot be worked out (no alkalinity; a sea unit with no salinity). No database. `pane`: instead of the wall,
    the pane of that unit (monitoring/_dock.html: its Big card with the line that names and closes it, as the dock
    beside the wall holds it). `cards_only`: the cards themselves, not their markup (`_strip`)."""
    from datetime import timedelta
    from uuid import UUID

    from farm.models import ProductionDepartment, SamplingPoint, Site, Tank
    from farm.water import calculation, parameters
    from farm.water.evaluate import Status
    from farm.water.read import Observation, Origin, PointWater, Reading
    from monitoring import read
    from monitoring.cards import builtin, resolve

    def row(**bounds):
        return N(**{'critical_low': None, 'warning_low': None, 'warning_high': None, 'critical_high': None,
                    **{name: Decimal(value) for name, value in bounds.items()}})

    limit_rows = {'oxygen_mg_l': [row(critical_low='6', warning_low='7')],
                  'co2_mg_l': [row(warning_high='15', critical_high='20')],
                  'nh3_n_mg_l': [row(warning_high='0.0100', critical_high='0.0125')],
                  'alkalinity_mg_l': [row(warning_low='70', warning_high='150')]}
    site = Site(name='Bergen Hatchery', code='BG', timezone='Europe/Oslo', altitude=Decimal('12'))
    hall = ProductionDepartment(name='Hatchery hall A', site=site)
    small = N(pk=builtin.SMALL, shown_name='Small', expanded_id=builtin.DETAILED, measure=builtin.SMALL_MEASURE)
    chosen = resolve.Resolved(small, builtin.SMALL_LAYOUT, resolve.VIEW, flip_to=N(shown_name='Detailed'))
    species = N(common_name='Atlantic salmon', local_name='')
    cards = []
    with translation.override(language):
        for index, (code, name, oxygen, status, temperature, ph, alkalinity, tan, hours, extra) in enumerate(_WALL):
            # (a fixed id: the part must be the same text at every run)
            unit = Tank(id=UUID(int=1000 + index), code=code, name=name, production_department=hall,
                        kind='cage' if code.startswith('TG') else 'tank',
                        status='maintenance' if extra == 'maintenance' else 'active',
                        water_type='saltwater' if extra == 'sea' else 'freshwater')
            point = SamplingPoint(unit=unit, name='Middle', kind='middle')
            at = NOW - timedelta(hours=hours)

            def reading(code, value, status=Status.OK, channel=None, limit=None):
                observation = Observation(point, at, Origin.SENSOR if channel else Origin.MANUAL, {code: Decimal(value)},
                                          channel_no=channel, fresh_for=180 if channel else None)
                judged = Status.OK if status == Status.STALE else status
                return Reading(parameters.get(code), Decimal(value), observation, status=status, judged=judged,
                               limits=[limit] if limit is not None else [])

            old = Status.STALE if status == 'stale' else Status.OK
            found = [reading('temperature_c', temperature, old, 57 + index),
                     reading('oxygen_mg_l', oxygen, Status(status), 58 + index, limit_rows['oxygen_mg_l'][0]),
                     reading('oxygen_saturation_pct', '98.0' if status in ('ok', 'stale') else '71.5', old, 58 + index),
                     reading('ph', ph, Status.CRITICAL if extra == 'second' else old, 59 + index,
                             row(critical_low='6.8') if extra == 'second' else None),
                     reading('tan_mg_l', tan, old)]
            if alkalinity:
                found.append(reading('alkalinity_mg_l', alkalinity, old, limit=limit_rows['alkalinity_mg_l'][0]))
            water = PointWater(point, {each.code: each for each in found}, for_unit=True)
            with mock.patch('farm.water.read.limits_of', return_value={unit.pk: limit_rows}):
                chart = calculation.charts_of([unit], {unit.pk: [water]}, NOW)[unit.pk]
            stock = None if extra == 'empty' else N(
                over_capacity=False, shares=[N(batch=N(species=species, code=f'B-2026-{index:03d}'))],
                count=1000 + 137 * index, biomass_kg=Decimal(66 + 31 * index), density=Decimal('23.6') + index,
                avg_weight_g=Decimal('92.4'))
            withdrawal = (N(batch=N(code='B-2026-004'), until=date(2026, 11, 25)),) if extra == 'withdrawal' else ()
            cards.append(read.Card(unit=unit, template=chosen, today=NOW.date(), stock=stock, water=(water,),
                                   withdrawal=withdrawal, sections=frozenset(read.SECTIONS), now=NOW, chart=chart,
                                   ph_scale=(6.4, 8.6)))
        if cards_only:
            return cards
        if pane:
            from dataclasses import replace
            big = N(pk=builtin.BIG, shown_name='Big', expanded_id=builtin.DETAILED, measure=builtin.BIG_MEASURE)
            card = replace(next(card for card in cards if card.unit.code == pane),
                           template=resolve.Resolved(big, builtin.BIG_LAYOUT, resolve.VIEW))
            views = [{'label': label, 'current': label == 'Close-up', 'url': '#', 'poll': '#'}
                     for label in ('Close-up', 'Full scale')]
            return render_to_string('monitoring/_dock.html', {
                'pane': {'row': {'card': card, 'flip': {}, 'zoom': views, 'pane': True, 'ns': 'pane-'},
                         'pane_unit': card.unit, 'close_url': '#'},
                'pane_poll_url': '#', 'poll_seconds': 15})
        openers = {card.unit.pk: {'page': '#', 'into': '', 'open': card.unit.code == 'HA-R02'} for card in cards}
        return render_to_string('monitoring/_grid.html', {
            'openers': openers,
            'rows': [{'card': card, 'flip': {'page': '#', 'poll': '#'}, 'open': openers[card.unit.pk]} for card in cards],
            'band': read.band(cards),
            'modes': [{'label': label, 'url': '#', 'current': label == 'Small', 'id': label.lower()}
                      for label in ('Small', 'Simple', 'Detailed')],
            'computed_at': NOW.replace(tzinfo=None), 'count_line': '20 of 25 units shown'})


def _strip(alarms=0):
    """The new look's status strip (core/_strip.html) as the server prints it beside the wall (`_wall('en')`): its units
    counted on their cards' rungs, as alarms.read counts them, with `alarms` open alarms (none: a server whose alarm engine
    is not running), worded and linked by core.ui.alarms_item for a person who may open Monitoring and Alarms.
    frontend/test/strip-link.browser.test.ts clicks it and must land on the page that lists what it counts."""
    from alarms.read import Attention
    from core import ui
    keys = [card.state.key for card in _wall('en', cards_only=True) if card.stock is not None]
    attention = Attention(alarms=alarms, alarms_critical=alarms, critical=keys.count('critical'),
                          warning=keys.count('warning'), blind=keys.count('blind'), unjudged=keys.count('unjudged'))
    items = [ui.alarms_item(attention, N(has_perm=lambda perm: True)),
             {'key': 'clock', 'url': '', 'status': '', 'text': '06.11.2026, 10:19 · Europe/Oslo'}]
    return render_to_string('core/_strip.html', {'items': items})


def _shell_next():
    """A whole page of the new look (templates/app_base.html, data-ui="next") with an island in it ({% island %}, the
    component gallery of the browser tests, frontend/test/gallery): the shell, the strip, the scripts and the island as
    the server prints them, for frontend/test/page.browser.test.ts to load under the server's own policy (its nonce is
    'layout'). Made-up menu and person; the asset URLs without their modification time and the island read from the test
    fixture manifest, so the part is the same on every machine."""
    from django.template import engines
    from django.urls import reverse

    from core import theme
    from core.templatetags import assets
    page = engines['django'].from_string(
        '{% extends "app_base.html" %}{% load assets %}{% block title %}Gallery{% endblock %}'
        '{% block heading %}Gallery{% endblock %}{% block content %}'
        '{% island "gallery" props label="Loading the gallery…" %}{% endblock %}')
    entry = {'label': 'Sites', 'url': '/farm/sites/', 'icon': 'building', 'current': True, 'badge': None, 'area': 'farm'}
    section = {'label': '', 'groups': [{'label': 'Facility', 'entries': [entry]}], 'collapsed': False, 'key': 'company-top',
               'current': True}
    workspace = {'key': 'company', 'label': 'Company', 'sections': [section], 'url': '/', 'badge': None}
    user = N(get_username=lambda: 'test.person', get_full_name=lambda: 'Test Person', email='test.person@example.com',
             is_authenticated=True)
    props = {'rows': [{'code': 'TK-01', 'name': 'Test Store', 'site': 'Test Site North', 'capacity': '5,000 kg',
                       'status': 'ok', 'word': 'Active'}],
             'errors': {'organisation_number': ['Enter nine digits, with or without spaces.']}}
    context = {
        'request': N(path='/farm/sites/', get_full_path=lambda: '/farm/sites/'), 'user': user, 'csp_nonce': 'layout',
        'csrf_token': 'layout-token', 'LANGUAGE_CODE': 'en', 'UI_NEXT': True, 'THEME': theme.DEFAULT_NEXT,
        'THEMES': theme.THEMES, 'workspaces': [workspace], 'workspace': workspace, 'rail_sections': [section],
        'bottom_bar': [entry], 'page_area': 'farm', 'page_icon': 'building', 'page_group': 'Facility',
        'page_panel': 'Company', 'page_label': 'Sites', 'props': props,
        'ui_strip': [{'key': 'alarms', 'url': reverse('alarms:alarm_list'), 'text': 'Reading the alarms…', 'status': ''},
                     {'key': 'clock', 'url': '', 'status': '', 'text': '06.11.2026, 10:19 · Europe/Oslo'}],
    }
    fixture = Path(settings.BASE_DIR, 'core', 'testdata', 'islands-manifest.json')
    with mock.patch.object(assets, 'versioned', side_effect=lambda path: assets.static(path)), \
            mock.patch.object(assets, 'manifest_path', return_value=str(fixture)):
        return page.render(context)


PAGES = {'meal': _meal, 'stock': _stock, 'water': _water, 'card-en': lambda: _card('en'), 'card-nb': lambda: _card('nb'),
         'matrix': _matrix, 'approve': _approve, 'tabs': _tabs, 'report-tabs': _report_tabs, 'overview': _overview,
         'wall-small-en': lambda: _wall('en'), 'wall-small-tr': lambda: _wall('tr'),
         'dock-big-tr': lambda: _wall('tr', pane='HA-R02'), 'shell-next': _shell_next,
         'strip-units': _strip, 'strip-split': lambda: _strip(alarms=1)}


def rendered():
    """{file name: what the templates print now}, at a fixed moment (an age said in a title stays the same)."""
    with translation.override('en'), mock.patch('django.utils.timezone.now', return_value=NOW):
        return {f'{name}.html': make().strip() + '\n' for name, make in PAGES.items()}


def stale():
    """The part files that differ from what the templates print now."""
    return sorted(name for name, text in rendered().items()
                  if not (FOLDER / name).exists() or (FOLDER / name).read_text(encoding='utf-8') != text)


def write():
    FOLDER.mkdir(parents=True, exist_ok=True)
    for name, text in rendered().items():
        (FOLDER / name).write_text(text, encoding='utf-8', newline='\n')
