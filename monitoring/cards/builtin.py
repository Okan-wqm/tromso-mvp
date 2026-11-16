"""The built-in card templates, as the code says them: Simple and Detailed reproduce the cards as they were before
templates, value for value (monitoring/tests/test_golden.py), Operator puts the oxygen and the temperature first
(offered, not a default: the owner decides after a trial on the wall), and Small is the overview card of a wide
monitor (owner decision 7, 2026-11-12): the state, the worst reason, the oxygen with its saturation, the temperature,
the pH, the calculated CO₂ and the pH window, FITTED (its measure in card units, catalogue.MEASURE_W), so every tank
of a hall is on one screen; Big is the card of one tank read from across the room (owner decisions 4, 10, 11, 12): its
four first values large, the unit's Deffeyes chart DOMINANT (more than half of the card), then every value with where
it came from and when, what to dose, the other sampling points and the stock, FITTED too. Migrations 0002, 0005 and
0006 froze the same layouts in the database (a test keeps the two
equal); a trigger keeps any writer from changing or deleting them, so a change to a built-in is a new migration, never
an edit. To change one for a farm, copy it.

Their names are English msgids, shown in the person's language (`CardTemplate.shown_name`)."""
from uuid import UUID

from django.utils.translation import gettext_noop

SIMPLE = UUID('5f1c2a6e-0000-4000-8000-00000000c001')
DETAILED = UUID('5f1c2a6e-0000-4000-8000-00000000c002')
OPERATOR = UUID('5f1c2a6e-0000-4000-8000-00000000c003')
SMALL = UUID('5f1c2a6e-0000-4000-8000-00000000c004')
BIG = UUID('5f1c2a6e-0000-4000-8000-00000000c005')
# The one global rule: every unit no other rule names gets Simple.
GLOBAL_RULE = UUID('5f1c2a6e-0000-4000-8000-00000000a001')


def _w(id, type, x, y, w, h, bind=None, opts=None):
    widget = {'id': id, 'type': type, 'x': x, 'y': y, 'w': w, 'h': h}
    if bind is not None:
        widget['bind'] = bind
    if opts is not None:
        widget['opts'] = opts
    return widget


SIMPLE_LAYOUT = {'schema': 1, 'widgets': [
    _w('w1', 'experiment', 0, 0, 12, 1),
    _w('w2', 'fish', 0, 1, 12, 5, opts={'figures': 'brief'}),
    _w('w3', 'feeding', 0, 6, 12, 3),
    _w('w4', 'water_table', 0, 9, 12, 4, opts={'points': 'middle', 'parameters': 'key'}),
    _w('w5', 'deffeyes', 0, 13, 4, 1),
]}

DETAILED_LAYOUT = {'schema': 1, 'widgets': [
    _w('w1', 'experiment', 0, 0, 12, 1),
    _w('w2', 'fish', 0, 1, 12, 7, opts={'figures': 'full'}),
    _w('w3', 'feeding', 0, 8, 12, 4, opts={'week': True}),
    _w('w4', 'water_table', 0, 12, 12, 8, opts={'points': 'all', 'parameters': 'all'}),
    _w('w5', 'health', 0, 20, 12, 4),
    _w('w6', 'tasks', 0, 24, 12, 2),
    _w('w7', 'deffeyes', 0, 26, 4, 1),
]}

OPERATOR_LAYOUT = {'schema': 1, 'widgets': [
    _w('w1', 'value', 0, 0, 6, 3, bind={'parameter': 'oxygen_mg_l'}, opts={'size': 'large'}),
    _w('w2', 'value', 6, 0, 6, 3, bind={'parameter': 'temperature_c'}, opts={'size': 'large'}),
    _w('w3', 'value', 0, 3, 4, 2, bind={'parameter': 'oxygen_saturation_pct'}),
    _w('w4', 'value', 4, 3, 4, 2, bind={'parameter': 'ph'}),
    _w('w5', 'value', 8, 3, 4, 2, bind={'parameter': 'tan_mg_l'}),
    _w('w6', 'experiment', 0, 5, 12, 1),
    _w('w7', 'fish', 0, 6, 12, 5, opts={'figures': 'brief'}),
    _w('w8', 'feeding', 0, 11, 12, 3),
    _w('w9', 'deffeyes', 0, 14, 4, 1),
]}

# Five rows of a card 31 units wide and 12 high: four values on three rows (label, figure, and under it where the
# value came from and how old it is: always, review R1), the pH window on two.
SMALL_LAYOUT = {'schema': 1, 'widgets': [
    _w('w1', 'value', 0, 0, 3, 3, bind={'parameter': 'oxygen_mg_l'}),
    _w('w2', 'value', 3, 0, 3, 3, bind={'parameter': 'temperature_c'}),
    _w('w3', 'value', 6, 0, 3, 3, bind={'parameter': 'ph'}),
    _w('w4', 'value', 9, 0, 3, 3, bind={'parameter': 'co2_calc_mg_l'}),
    _w('w5', 'ph_window', 0, 3, 12, 2),
]}
SMALL_MEASURE = (31, 12)

# Twenty-one rows of a card 48 units wide and 61 high: the four first values on two, the chart on twelve (four sevenths
# of the card's rows), every value of the middle point on five, then what to dose, the other points and the stock.
BIG_LAYOUT = {'schema': 1, 'widgets': [
    _w('w1', 'value', 0, 0, 3, 2, bind={'parameter': 'oxygen_mg_l'}),
    _w('w2', 'value', 3, 0, 3, 2, bind={'parameter': 'temperature_c'}),
    _w('w3', 'value', 6, 0, 3, 2, bind={'parameter': 'ph'}),
    _w('w4', 'value', 9, 0, 3, 2, bind={'parameter': 'co2_calc_mg_l'}),
    _w('w5', 'chart', 0, 2, 12, 12),
    _w('w6', 'water_table', 0, 14, 12, 5, opts={'points': 'middle', 'parameters': 'all'}),
    _w('w7', 'dosing', 0, 19, 4, 2),
    _w('w8', 'points', 4, 19, 4, 2),
    _w('w9', 'stock', 8, 19, 4, 2),
]}
BIG_MEASURE = (48, 61)

# {id: (name msgid, layout, the template its flip link shows)}
BUILTINS = {
    SIMPLE: (gettext_noop('Simple'), SIMPLE_LAYOUT, DETAILED),
    DETAILED: (gettext_noop('Detailed'), DETAILED_LAYOUT, SIMPLE),
    OPERATOR: (gettext_noop('Operator view'), OPERATOR_LAYOUT, DETAILED),
    SMALL: (gettext_noop('Small'), SMALL_LAYOUT, DETAILED),
    BIG: (gettext_noop('Big'), BIG_LAYOUT, DETAILED),
}
# {id: (width, height)} of the fitted built-ins, in card units.
MEASURES = {SMALL: SMALL_MEASURE, BIG: BIG_MEASURE}
