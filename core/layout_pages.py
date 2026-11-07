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


PAGES = {'stock': _stock, 'water': _water, 'card-en': lambda: _card('en'), 'card-nb': lambda: _card('nb'),
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
