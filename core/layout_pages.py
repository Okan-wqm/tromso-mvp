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


PAGES = {'meal': _meal, 'stock': _stock, 'water': _water, 'card-en': lambda: _card('en'), 'card-nb': lambda: _card('nb'),
         'matrix': _matrix, 'approve': _approve, 'tabs': _tabs}


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
