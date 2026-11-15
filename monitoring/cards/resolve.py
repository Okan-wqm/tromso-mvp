"""Which template a unit's card gets: one ladder, first hit wins.

    the screen's view  >  the board's row for the unit  >  a rule for the unit  >  for its system  >  for its system's type  >  for the
    species of its fish  >  for its kind  >  the board's default (no board: the page's own Simple/Detailed choice)  >
    the global rule  >  Simple from the code (no rule at all: a database flushed by a test, never a farm)

The screen's VIEW (`mode=small`, `mode=big`) is how the person at this screen looks at its units now: every card of it as that
template, on a board or not, whatever the rules say (owner decision 7, 2026-11-12: "the user chooses how a screen
shows the units", the overview shows EVERY unit as a small card); it is the address's, never stored. The board's row is
the person arranging this wall; the board's default sits below the rules, as its default mode did (owner decision 1). A flip (`?flip=`) shows the template's flip target and the link goes back. Only live templates and
live rules of live units, systems and species count: a rule or pointer to something deleted is passed over and counts
again when it is restored. A stored layout the validator refuses (a hand edit) never blanks a card: the card is drawn
with the built-in Detailed layout from the code, says "template error", and the error is logged once per template per
process.

`templates_for` loads the live templates and the live rules in TWO queries, whatever the number of units; the board's
rows come with the board, the units' systems with the units, the species from the stock the card read already holds."""
import logging
from dataclasses import dataclass, field

from django.db.models import Q
from django.utils.translation import gettext, gettext_lazy as _

from . import builtin, catalogue, validate

logger = logging.getLogger(__name__)

VIEW, ROW, UNIT, SYSTEM, SYSTEM_TYPE, SPECIES, KIND, BOARD, ADDRESS, GLOBAL, FLIP, FALLBACK, PREVIEW = (
    'view', 'row', 'unit', 'system', 'system_type', 'species', 'kind', 'board', 'address', 'global', 'flip', 'fallback',
    'preview')
BECAUSE = {
    VIEW: _('the view chosen on this screen'),
    ROW: _('chosen for this card on the board'),
    UNIT: _('the rule for this unit'),
    SYSTEM: _('the rule for its system'),
    SYSTEM_TYPE: _('the rule for its type of system'),
    SPECIES: _('the rule for its species'),
    KIND: _('the rule for its kind of unit'),
    BOARD: _('the board’s default'),
    ADDRESS: _('chosen on this page'),
    GLOBAL: _('the rule for every unit'),
    FLIP: _('flipped on this page'),
    FALLBACK: _('no rule applies'),
    PREVIEW: _('the layout being designed'),
}
# The templates a page's `mode=` chooses (no board), as the cards before templates did: below the rules.
ADDRESS_TEMPLATES = {'simple': builtin.SIMPLE, 'detailed': builtin.DETAILED}
# The views a screen's `mode=` chooses: every card of the screen as that template, above everything.
VIEW_TEMPLATES = {'small': builtin.SMALL, 'big': builtin.BIG}
# Templates whose stored layout was refused, logged once each in this process.
LOGGED = set()


@dataclass(frozen=True)
class Resolved:
    """A card's template: the template record (None: Simple from the code), the layout it is drawn with (upgraded to
    the current version), why it was chosen, whether its stored layout was refused (drawn as Detailed instead), whether
    the card is flipped, and the template its flip link shows (None: no link)."""
    template: object
    layout: dict
    why: str
    error: bool = False
    flipped: bool = False
    flip_to: object = None

    @property
    def because(self):
        return gettext(BECAUSE[self.why])

    @property
    def name(self):
        return self.template.shown_name if self.template is not None else gettext('Simple')

    @property
    def rows(self):
        """The rows its widgets take: the lowest edge of any of them."""
        return max((widget['y'] + widget['h'] for widget in self.layout['widgets']), default=0)

    @property
    def measure(self):
        """(width, height) in card units when the card is drawn FITTED (the template has a measure, its widgets take at
        most catalogue.FIT_ROWS rows and its stored layout could be drawn), else None: the card then flows as cards
        always did. The one answer the card, its widgets and the page's wall ask."""
        measure = getattr(self.template, 'measure', None)
        return measure if measure and not self.error and 0 < self.rows <= catalogue.FIT_ROWS else None

    @property
    def fill(self):
        """A FULL-HEIGHT card: fitted, and higher than it is wide (the Big card). A wall gives it a whole row of the
        screen and turns pages rather than set more of them side by side (monitoring/cards/slots.py FILL)."""
        measure = self.measure
        return bool(measure) and measure[1] > measure[0]

    @property
    def fit_classes(self):
        """The classes of a fitted card and of its grid (static/css/card-grid.css): ('is-fit mw-31 mh-10', 'gr-5')."""
        width, height = self.measure
        return f'is-fit mw-{width} mh-{height}', f'gr-{self.rows}'


class Rules:
    """The live rules, indexed by scope (one rule per scope: the database holds it)."""

    def __init__(self, rules):
        self.all = list(rules)
        self.by = {}
        for each in self.all:
            for scope in ('unit_id', 'system_id', 'system_type', 'species_id', 'kind'):
                if getattr(each, scope) is not None:
                    self.by[(scope, getattr(each, scope))] = each.template_id
                    break
            else:
                self.by[('global', None)] = each.template_id

    def get(self, scope, value):
        return self.by.get((scope, value)) if value is not None or scope == 'global' else None


@dataclass(frozen=True)
class Choice:
    """What the page chooses: the screen's view (`mode=small`: every card as that template), the board's rows
    ({unit id: template id}) and default, or with no board the page's own template (`mode=simple|detailed`), and the
    units flipped. `chart`: the view the screen's charts are drawn in ('' close, 'full' full scale: `?chart=full`), and
    `zoom`: the units whose chart is drawn in the other view (`?zoom=<unit>,...`)."""
    rows: dict = field(default_factory=dict)
    board: object = None
    address: object = None
    flip: frozenset = frozenset()
    preview: object = None          # a Resolved every card is drawn with (the designer's preview), no query
    view: object = None             # the template every card of the screen is drawn with (VIEW_TEMPLATES)
    chart: str = ''
    zoom: frozenset = frozenset()

    @classmethod
    def of(cls, board, params):
        view = VIEW_TEMPLATES.get(params.mode)
        if board is not None:
            return cls(rows={row.unit_id: row.template_id for row in board.rows.all() if row.template_id},
                       board=board.default_template_id, flip=params.flip, view=view, chart=params.chart,
                       zoom=params.zoom)
        return cls(address=ADDRESS_TEMPLATES.get(params.mode), flip=params.flip, view=view, chart=params.chart,
                   zoom=params.zoom)


def _layout(template):
    """(layout, error) of a template: its layout upgraded, or the built-in Detailed one when the validator refuses it."""
    problems = [problem for problem in validate.validate(template.layout) if problem.severity == validate.ERROR]
    if not problems:
        return validate.upgrade(template.layout), False
    if (template.pk, template.version) not in LOGGED:
        LOGGED.add((template.pk, template.version))
        logger.error('Card template %s (%s) has a layout the validator refuses (%s); its cards are drawn with the '
                     'built-in Detailed layout.', template.pk, template.name,
                     '; '.join(f'{problem.widget} {problem.code}' for problem in problems))
    return builtin.DETAILED_LAYOUT, True


def _resolved(template, why, templates, flipped=False, flip_to=None):
    layout, error = _layout(template)
    if not flipped:
        flip_to = templates.get(template.expanded_id)
    return Resolved(template, layout, why, error, flipped, flip_to)


def template_of(unit, species_id, row_template, board_template, rules, templates, flipped=False, board_why=BOARD,
                view=None):
    """Resolved of one unit's card (pure: `rules` a Rules, `templates` {id: live template}). `board_template` is the
    board's default, or with no board the page's own choice (`board_why` ADDRESS); `view` the screen's view."""
    system = unit.system if unit.system_id else None
    ladder = ((VIEW, view), (ROW, row_template), (UNIT, rules.get('unit_id', unit.pk)),
              (SYSTEM, rules.get('system_id', unit.system_id)),
              (SYSTEM_TYPE, rules.get('system_type', system.type if system is not None else None)),
              (SPECIES, rules.get('species_id', species_id)), (KIND, rules.get('kind', unit.kind)),
              (board_why, board_template), (GLOBAL, rules.get('global', None)))
    for why, pk in ladder:
        template = templates.get(pk) if pk is not None else None
        if template is not None:
            break
    else:
        return Resolved(None, builtin.SIMPLE_LAYOUT, FALLBACK)
    if flipped:
        target = templates.get(template.expanded_id)
        if target is not None:
            return _resolved(target, FLIP, templates, flipped=True, flip_to=template)
    return _resolved(template, why, templates)


def templates_for(units, species_of, choice):
    """{unit id: Resolved} of the units ({unit id: species id} of the stocked ones), in two queries."""
    if choice.preview is not None:
        return {unit.pk: choice.preview for unit in units}
    from ..models import CardTemplate, CardTemplateAssignment
    templates = {template.pk: template for template in CardTemplate.objects.all()}
    rules = Rules(CardTemplateAssignment.objects.filter(
        Q(unit__isnull=True) | Q(unit__is_deleted=False), Q(system__isnull=True) | Q(system__is_deleted=False),
        Q(species__isnull=True) | Q(species__is_deleted=False)).only(
        'template_id', 'unit_id', 'system_id', 'system_type', 'species_id', 'kind'))
    board, why = (choice.board, BOARD) if choice.board is not None else (choice.address, ADDRESS)
    return {unit.pk: template_of(unit, species_of.get(unit.pk), choice.rows.get(unit.pk), board, rules, templates,
                                 str(unit.pk) in choice.flip, why, choice.view)
            for unit in units}
