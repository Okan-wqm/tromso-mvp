"""THE one validator of a card template's layout: pure (no model, no query), the same function for the model's clean,
the form field, the designer's preview and the tests. `validate(layout) -> [Problem]`; an error blocks saving, a warning
never does. The database holds what SQL can (an object, a list of at most 40 widgets, 32 KB, the version stamp:
monitoring/models.py); everything that needs the catalogue is here, once.

A layout (version 1) is flat, so a widget cannot be half-described:

    {"schema": 1, "widgets": [{"id": "w1", "type": "value", "x": 0, "y": 0, "w": 3, "h": 2,
                               "bind": {"parameter": "oxygen_mg_l"}, "opts": {"size": "large"}}]}

An older version is upgraded first (`upgrade`, one pure function per step in UPGRADES) and checked as upgraded; the
stored layout is never changed by a check. The geometry (bounds, sizes, overlaps) is mirrored by frontend/grid for the
designer and both run monitoring/tests/layout_vectors.json; compaction exists only there (the server never moves a
widget)."""
import json
import re
from collections import namedtuple

from django.core.exceptions import ValidationError
from django.utils.translation import gettext, gettext_lazy as _

from farm.models.water_point import PointKind

from . import catalogue

ERROR, WARNING = 'error', 'warning'
ID = re.compile(r'^[a-z][a-z0-9_-]{0,15}$')
REQUIRED = {'id', 'type', 'x', 'y', 'w', 'h'}
OPTIONAL = {'bind', 'opts'}
BIND_KEYS = {'parameter', 'point'}
GEOMETRY = ('bounds', 'size', 'overlap')

MESSAGES = {
    'shape': _('A layout is a set of named values with a list of widgets, and nothing else.'),
    'schema': _('This layout is of an unknown version (%(version)s).'),
    'too_many': _('A card holds at most %(max)d widgets.'),
    'too_large': _('This layout is too large to store.'),
    'keys': _('Widget %(widget)s has a field it may not have, or lacks one it needs.'),
    'id': _('Each widget needs a short name: a lower-case letter, then up to 15 letters, digits, - or _.'),
    'duplicate': _('Two widgets are called %(widget)s.'),
    'type': _('Widget %(widget)s is of a kind the card does not know.'),
    'disabled': _('Widget %(widget)s: %(label)s cannot be placed yet.'),
    'number': _('Widget %(widget)s: its place and size must be whole numbers.'),
    'bounds': _('Widget %(widget)s lies outside the card (12 columns, from the top).'),
    'size': _('Widget %(widget)s must be from %(min_w)d×%(min_h)d to %(max_w)d×%(max_h)d cells.'),
    'overlap': _('Widgets %(widget)s and %(other)s overlap.'),
    'binding': _('Widget %(widget)s: choose the water parameter it shows (and, if not the middle, its point).'),
    'unbound': _('Widget %(widget)s shows no single water parameter: it cannot be bound to one.'),
    'option': _('Widget %(widget)s: %(detail)s'),
    'no_oxygen': _('No widget shows the oxygen.'),
    'large': _('More than two widgets are large: the large ones no longer stand out.'),
    'many': _('More than %(count)d widgets: a card this full is hard to read from a distance.'),
    # a FITTED template (one with a measure): what cannot stand on it, and what would not be read on it
    'fit_look': _('Widget %(widget)s: %(label)s has no fitted look and would be cut on a fitted card. Remove it, or '
                  'leave the card’s width and height empty.'),
    'fit_rows': _('A fitted card’s widgets share its height in at most %(most)d rows; this layout takes %(rows)d.'),
    'fit_low': _('Widget %(widget)s: at this measure its place is about %(has)s units high and %(label)s needs '
                 '%(needs)s: give it more rows, or the card more height.'),
    'fit_narrow': _('Widget %(widget)s: at this measure its place is about %(has)s units wide and %(label)s needs '
                    '%(needs)s: give it more columns, or the card more width.'),
    'needs_fit': _('Widget %(widget)s: %(label)s is made for a fitted card. Give the template a width and a height.'),
}
# The codes whose message names the widget.
ABOUT_A_WIDGET = {'keys', 'duplicate', 'type', 'disabled', 'number', 'bounds', 'size', 'overlap', 'binding', 'unbound',
                  'option', 'fit_look', 'fit_low', 'fit_narrow', 'needs_fit'}
# The errors that are about the template's measure, not about the layout alone (the form puts them on the measure).
FITTED_ERRORS = ('fit_look', 'fit_rows')
_('“%(option)s” is not an option of this widget.'), _('“%(option)s” has no value.')
_('the options must be a set of named values.')


class Problem(namedtuple('Problem', 'severity widget code params')):
    """One finding: its severity, the widget's id ('' for the layout), a code of MESSAGES and its parameters as a
    tuple of (name, value) pairs (hashable, so a problem can be compared and collected)."""

    @property
    def message(self):
        return gettext(MESSAGES[self.code]) % {'widget': self.widget, **dict(self.params)}

    def as_data(self):
        return {'severity': self.severity, 'widget': self.widget, 'code': self.code, 'message': self.message}


def _error(widget, code, **params):
    return Problem(ERROR, widget, code, tuple(params.items()))


def _warning(code, **params):
    return Problem(WARNING, '', code, tuple(params.items()))


# ---- versions ----------------------------------------------------------------------------------------------------
# {version n: a pure function from a layout of version n to one of version n + 1}. Empty while there is one version.
UPGRADES = {}


def _version(layout):
    version = layout.get('schema')
    return version if type(version) is int else None


def upgrade(layout):
    """The layout in the current version: itself when it is current, else a new layout made one step at a time;
    the given one is never changed."""
    version = _version(layout)
    while version is not None and version < catalogue.SCHEMA_VERSION:
        layout = UPGRADES[version](layout)
        version = _version(layout)
    return layout


# ---- the check ---------------------------------------------------------------------------------------------------
def _is_int(value):
    return type(value) is int


def validate(layout, measure=None):
    """[Problem] of a layout, errors and warnings, in a stable order: the layout's, then each widget's in the widgets'
    order (keys, id, type, numbers, bounds, size, binding, options), then each overlapping pair, then what a FITTED
    card refuses (`measure`: the template's (width, height) in card units, None for a card that flows), then the
    warnings."""
    if not isinstance(layout, dict) or set(layout) != {'schema', 'widgets'} or not isinstance(layout['widgets'], list) \
            or not all(isinstance(each, dict) for each in layout['widgets']):
        return [_error('', 'shape')]
    version = _version(layout)
    if version is None or not 1 <= version <= catalogue.SCHEMA_VERSION:
        return [_error('', 'schema', version=layout.get('schema'))]
    layout = upgrade(layout)
    widgets = layout['widgets']
    problems = []
    if len(widgets) > catalogue.MAX_WIDGETS:
        problems.append(_error('', 'too_many', max=catalogue.MAX_WIDGETS))
    if len(json.dumps(layout, ensure_ascii=False).encode()) > catalogue.MAX_BYTES:
        problems.append(_error('', 'too_large'))
    placed, seen = [], set()
    for widget in widgets:
        found, rect = _widget(widget, seen)
        problems += found
        if rect is not None:
            placed.append((widget['id'], rect))
    problems += _overlaps(placed)
    if not any(problem.severity == ERROR for problem in problems):
        problems += _fitted_errors(widgets, measure)
    if not any(problem.severity == ERROR for problem in problems):
        problems += _warnings(widgets) + _look_warnings(widgets, measure)
    return problems


def _label(widget):
    return str(catalogue.WIDGETS[widget['type']].label)


def _fitted_errors(widgets, measure):
    """What a fitted card refuses (review R7: a widget with no fitted look was cut on a wall without a word)."""
    if not measure:
        return []
    problems = [_error(widget['id'], 'fit_look', label=_label(widget)) for widget in widgets
                if catalogue.FIT not in catalogue.WIDGETS[widget['type']].looks]
    rows = max((widget['y'] + widget['h'] for widget in widgets), default=0)
    if rows > catalogue.FIT_ROWS:
        problems.append(_error('', 'fit_rows', most=catalogue.FIT_ROWS, rows=rows))
    return problems


def fitted_place(widget, rows, measure):
    """(width, height) of a widget's place on a fitted card of `measure`, in card units, about: the card's width less
    its padding shared by the twelve columns, its height less the frame shared by the layout's rows."""
    width, height = measure
    return (widget['w'] / catalogue.COLUMNS * (width - catalogue.FIT_SIDES),
            widget['h'] * (height - catalogue.FIT_FRAME) / max(rows, 1))


def _look_warnings(widgets, measure):
    """Advice about the look: on a fitted card, a place too low or too narrow for what the widget prints there; on a
    card that flows, a widget made for a fitted one."""
    def said(value):
        return f'{value:.1f}'

    problems = []
    rows = max((widget['y'] + widget['h'] for widget in widgets), default=0)
    for widget in widgets:
        spec = catalogue.WIDGETS[widget['type']]
        if not measure:
            if catalogue.FLOW not in spec.looks:
                problems.append(Problem(WARNING, widget['id'], 'needs_fit', (('label', _label(widget)),)))
            continue
        wide, high = fitted_place(widget, rows, measure)
        for code, has, needs in (('fit_low', high, spec.fit_units[1]), ('fit_narrow', wide, spec.fit_units[0])):
            if has < needs:
                problems.append(Problem(WARNING, widget['id'], code, (
                    ('label', _label(widget)), ('has', said(has)), ('needs', said(needs)))))
    return problems


def _widget(widget, seen):
    """([Problem], (x, y, w, h) or None) of one widget; the rectangle when its place is whole numbers."""
    name = widget.get('id')
    label = name if isinstance(name, str) else ''
    if not isinstance(name, str) or not ID.match(name):
        return [_error(label, 'id')], None
    if name in seen:
        return [_error(name, 'duplicate')], None
    seen.add(name)
    if not REQUIRED <= set(widget) or set(widget) - REQUIRED - OPTIONAL:
        return [_error(name, 'keys')], None
    spec = catalogue.WIDGETS.get(widget['type']) if isinstance(widget['type'], str) else None
    if spec is None:
        return [_error(name, 'type')], None
    if not spec.enabled:
        return [_error(name, 'disabled', label=str(spec.label))], None
    x, y, w, h = (widget[key] for key in ('x', 'y', 'w', 'h'))
    if not all(_is_int(value) for value in (x, y, w, h)):
        return [_error(name, 'number')], None
    problems = geometry(name, spec, x, y, w, h)
    problems += _binding(name, spec, widget.get('bind'), 'bind' in widget)
    problems += _options(name, spec, widget.get('opts', {}))
    return problems, (x, y, w, h)


def geometry(name, spec, x, y, w, h):
    """The bounds and size problems of one placed widget (what frontend/grid mirrors)."""
    problems = []
    if x < 0 or y < 0 or x + w > catalogue.COLUMNS or y + h > catalogue.ROWS:
        problems.append(_error(name, 'bounds'))
    if not (spec.min_w <= w <= spec.max_w and spec.min_h <= h <= spec.max_h):
        problems.append(_error(name, 'size', min_w=spec.min_w, min_h=spec.min_h, max_w=spec.max_w, max_h=spec.max_h))
    return problems


def _binding(name, spec, bind, present):
    if spec.bind == catalogue.NONE:
        return [_error(name, 'unbound')] if present else []
    if not isinstance(bind, dict) or not set(bind) <= BIND_KEYS or not isinstance(bind.get('parameter'), str) \
            or bind['parameter'] not in catalogue.bindable() \
            or ('point' in bind and bind['point'] not in PointKind.values):
        return [_error(name, 'binding')]
    return []


def _options(name, spec, opts):
    if not isinstance(opts, dict):
        return [_error(name, 'option', detail=gettext('the options must be a set of named values.'))]
    known = {entry['name'] for entry in spec.options.entries}
    for option in sorted(set(opts) - known):
        return [_error(name, 'option', detail=gettext('“%(option)s” is not an option of this widget.')
                       % {'option': option})]
    for option in sorted(option for option, value in opts.items() if value is None):
        # (the designer leaves an option out rather than store it empty: one spelling for one choice)
        return [_error(name, 'option', detail=gettext('“%(option)s” has no value.') % {'option': option})]
    try:
        spec.options.check(opts)
    except ValidationError as error:
        return [_error(name, 'option', detail=' '.join(error.messages))]
    return []


def _overlaps(placed):
    """An overlap problem for each overlapping pair, once, (first, second) in the widgets' order."""
    problems = []
    for index, (name, (x, y, w, h)) in enumerate(placed):
        for other, (ox, oy, ow, oh) in placed[index + 1:]:
            if x < ox + ow and ox < x + w and y < oy + oh and oy < y + h:
                problems.append(_error(name, 'overlap', other=other))
    return problems


def shows_oxygen(widget):
    if widget['type'] == 'water_table':
        return True
    return widget['type'] in ('value', 'bar') and widget.get('bind', {}).get('parameter') in catalogue.OXYGEN


def _warnings(widgets):
    """Advice that never blocks a save: no oxygen anywhere on a card of fish, too many large widgets, too many widgets."""
    problems = []
    if widgets and not any(shows_oxygen(widget) for widget in widgets):
        problems.append(_warning('no_oxygen'))
    if sum(widget.get('opts', {}).get('size') == 'large' for widget in widgets) > catalogue.MAX_LARGE:
        problems.append(_warning('large'))
    if len(widgets) > catalogue.MANY_WIDGETS:
        problems.append(_warning('many', count=catalogue.MANY_WIDGETS))
    return problems


def clean(layout):
    """Raises ValidationError with the errors' messages (warnings never block), each naming its widget."""
    errors = [problem.message for problem in validate(layout) if problem.severity == ERROR]
    if errors:
        raise ValidationError(errors)
