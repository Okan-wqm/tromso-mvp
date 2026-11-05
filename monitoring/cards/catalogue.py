"""The widget catalogue: THE one truth of what a card template can hold. The designer's palette and inspector, the
validator (validate.py), the sources a wall reads (monitoring/read.py `needs`), the renderer and the tests all derive
from `WIDGETS`; the TypeScript receives it as data (`as_data`, through json_script) and holds no widget knowledge of
its own.

A widget is a PRESENTATION of a field the card read already holds (monitoring/read.py `Card`): it reads nothing and
works nothing out. Its options say how it is drawn, never what a figure is: no colour, font, threshold, unit or free
text (a threshold is the water limits', a unit and a precision the parameter's, a colour the state's). They are
`core.schema.Schema` descriptors, so the form, the validator and the designer read the same rule.

The grid is COLUMNS wide (a constant here, not stored: one place); a widget's place is (x, y) in cells from the top
left, its size (w, h) in cells, within its spec's bounds. The frame of a card (unit, state, reasons, withdrawal,
basis, flip link) is not a widget: a template cannot move, shrink or remove it."""
from dataclasses import dataclass

from django.utils.translation import gettext, gettext_lazy as _

from core.schema import Schema
from farm.models.water_point import PointKind
from farm.water import parameters

COLUMNS = 12
SCHEMA_VERSION = 1              # the layout version this code writes; older ones are upgraded (validate.UPGRADES)
MAX_WIDGETS = 40
MAX_BYTES = 32768
MANY_WIDGETS = 16               # more than this is a warning: a card that full is hard to read from a distance
MAX_LARGE = 2                   # more large widgets than this is a warning: large no longer stands out

# What a widget is bound to: nothing, or one water parameter (at the middle point unless it names another).
NONE, PARAMETER = 'none', 'parameter'

SIZE = {'name': 'size', 'label': 'Size', 'type': 'select', 'defaultValue': 'normal',
        'options': [{'value': 'normal', 'label': 'Normal'}, {'value': 'large', 'label': 'Large'}]}
_('Size'), _('Normal'), _('Large')                              # (msgids of the schemas, for the catalogs)


def _schema(*fields):
    return Schema({'fields': list(fields)})


@dataclass(frozen=True)
class WidgetSpec:
    type: str
    label: object               # a lazy msgid
    min_w: int
    min_h: int
    max_w: int
    max_h: int
    default_w: int
    default_h: int
    sources: tuple              # the card read's sources it shows (monitoring/read.py SOURCES)
    bind: str = NONE
    options: Schema = None
    enabled: bool = True        # False: catalogued, refused by the validator until what it needs exists
    on_empty: bool = False      # also drawn on the card of a unit with no fish

    @property
    def renderer(self):
        return f'monitoring/widgets/_{self.type}.html'


def _spec(type, label, minimum, maximum, default, sources, **extra):
    extra.setdefault('options', _schema())
    return WidgetSpec(type, label, *minimum, *maximum, *default, sources, **extra)


WIDGETS = {spec.type: spec for spec in (
    _spec('value', _('Value'), (2, 2), (6, 4), (3, 2), ('water',), bind=PARAMETER, options=_schema(SIZE)),
    _spec('bar', _('Value against its limits'), (3, 2), (12, 3), (4, 2), ('water',), bind=PARAMETER,
          options=_schema(SIZE)),
    _spec('water_table', _('Water'), (4, 2), (12, 12), (12, 4), ('water',), options=_schema(
        {'name': 'points', 'label': 'Points', 'type': 'select', 'defaultValue': 'middle',
         'options': [{'value': 'middle', 'label': 'The middle point'}, {'value': 'all', 'label': 'Every active point'}]},
        {'name': 'parameters', 'label': 'Parameters', 'type': 'select', 'defaultValue': 'key',
         'options': [{'value': 'key', 'label': 'The key values'}, {'value': 'all', 'label': 'Every value measured'}]})),
    _spec('fish', _('Fish'), (4, 3), (12, 8), (12, 5), ('stock',), options=_schema(
        {'name': 'figures', 'label': 'Figures', 'type': 'select', 'defaultValue': 'brief',
         'options': [{'value': 'brief', 'label': 'The key figures'}, {'value': 'full', 'label': 'Every figure'}]})),
    _spec('feeding', _('Feeding'), (4, 2), (12, 6), (12, 3), ('feeding',), options=_schema(
        {'name': 'week', 'label': 'The week too (feed rate, last fed, feed in use)', 'type': 'boolean'})),
    _spec('health', _('Health'), (4, 2), (12, 8), (12, 3), ('events', 'treatments', 'lice')),
    _spec('tasks', _('Tasks'), (3, 2), (12, 3), (6, 2), ('tasks',)),
    _spec('experiment', _('Experiments'), (3, 1), (12, 2), (12, 1), ('chips',), on_empty=True),
    _spec('deffeyes', _('Deffeyes chart'), (2, 1), (6, 2), (4, 1), ('water',), on_empty=True),
    _spec('spark', _('Trend'), (3, 2), (12, 4), (6, 2), ('water',), bind=PARAMETER, enabled=False),
)}
_('Points'), _('The middle point'), _('Every active point'), _('Parameters'), _('The key values')
_('Every value measured'), _('Figures'), _('The key figures'), _('Every figure')
_('The week too (feed rate, last fed, feed in use)')

# The water values the key-values table shows, from the middle point (the parameters' own short labels).
KEY_WATER = (parameters.TEMPERATURE, parameters.OXYGEN_MG_L, parameters.OXYGEN_PCT, parameters.PH, parameters.TAN)
OXYGEN = (parameters.OXYGEN_MG_L, parameters.OXYGEN_PCT)


def bindable():
    """The parameter codes a widget may be bound to: every parameter the water module knows, measured or worked out."""
    return list(parameters.BY_CODE)


def as_data():
    """The catalogue as plain data in the person's language, for the designer (json_script): the grid, each widget's
    sizes, binding, options (the Schema's own descriptors with their texts translated) and whether it may be placed,
    the parameters and the points a binding may name."""
    def translated(entry):
        shown = {**entry, 'label': _translated(entry)}
        if 'options' in entry:
            shown['options'] = [{**option, 'label': _translated(option)} for option in entry['options']]
        return shown

    return {
        'columns': COLUMNS, 'schema': SCHEMA_VERSION, 'max_widgets': MAX_WIDGETS,
        'widgets': [{'type': spec.type, 'label': str(spec.label), 'min_w': spec.min_w, 'min_h': spec.min_h,
                     'max_w': spec.max_w, 'max_h': spec.max_h, 'default_w': spec.default_w,
                     'default_h': spec.default_h, 'bind': spec.bind, 'enabled': spec.enabled,
                     'options': [translated(entry) for entry in spec.options.entries]}
                    for spec in WIDGETS.values()],
        'parameters': [{'value': parameter.code, 'label': str(parameter.label), 'short': str(parameter.short)}
                       for parameter in parameters.BY_CODE.values()],
        'points': [{'value': value, 'label': str(label)} for value, label in PointKind.choices],
    }


def _translated(described):
    """The label of a descriptor (a msgid) in the person's language."""
    msgid = described['label']
    return gettext(msgid)
