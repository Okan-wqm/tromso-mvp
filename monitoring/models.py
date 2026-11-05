"""What the monitoring cards store: named, shared wall boards (the units on them and how each card is drawn), and the card
templates with the rules that say which unit's card gets which. A figure, a state, a token or a chart is never stored: a
card is worked out from the other apps' records every time it is asked for (monitoring/read.py). Window places are kept
per device in the browser, not here.

Rules the database can hold are constraints (a board's name unique among live boards, case-insensitively, and not blank;
the modes and the refresh seconds in their ranges; one card per unit per board; a template's layout shape, size and
version; one scope per rule and one live rule per scope; the built-ins unchangeable, by a trigger); the form mirrors them
for friendly messages. That a board holds only live units is not a row fact (liveness is soft-delete state), so it is the
form's choices and the read's live join."""
from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Case, F, Q, Value, When
from django.db.models.fields.json import KeyTransform
from django.db.models.functions import Cast, Coalesce, Lower
from django.db.models.lookups import Exact, LessThanOrEqual
from django.utils.translation import gettext, gettext_lazy as _

from core.models import AuditedModel
from farm.models import Species, System, Tank

from .cards import builtin, catalogue

BUILTIN_IDS = tuple(builtin.BUILTINS)

SIMPLE, DETAILED = 'simple', 'detailed'
REFRESH_MIN, REFRESH_MAX = 10, 600


class CardWidth(models.IntegerChoices):
    """How wide a board's cards are at the least (the CSS --card-min of the wall): a board arranges a wall, so its width
    is the board's, never a template's."""
    COMPACT = 1, _('Compact')
    AUTO = 2, _('Automatic')
    COMFORTABLE = 3, _('Comfortable')


class CardMode(models.TextChoices):
    SIMPLE = SIMPLE, _('Simple')
    DETAILED = DETAILED, _('Detailed')


class MonitorBoard(AuditedModel):
    """A named wall screen shared by everyone who may read the Monitoring page: which units it shows and how each card is
    drawn. Deleting one is an ordinary soft delete (nothing depends on it); restoring brings its units back."""

    name = models.CharField(_('Name'), max_length=100)
    description = models.CharField(_('Description'), max_length=300, blank=True, default='')
    default_mode = models.CharField(_('Cards are'), max_length=10, choices=CardMode.choices, default=SIMPLE)
    # Empty: the system's own interval (settings.MONITOR_POLL_SECONDS).
    refresh_seconds = models.PositiveSmallIntegerField(
        _('Refresh every (seconds)'), null=True, blank=True,
        validators=[MinValueValidator(REFRESH_MIN), MaxValueValidator(REFRESH_MAX)])
    # The template of a card no rule names (below the rules: as default_mode was); empty: the global rule's.
    default_template = models.ForeignKey('CardTemplate', null=True, blank=True, on_delete=models.SET_NULL,
                                         related_name='default_for_boards', verbose_name=_('Cards are drawn with'))
    card_width = models.PositiveSmallIntegerField(_('Card width'), choices=CardWidth.choices, default=CardWidth.AUTO)

    class Meta:
        db_table = 'monitor_boards'
        ordering = ['name']
        verbose_name = _('monitoring board')
        verbose_name_plural = _('monitoring boards')
        constraints = [
            models.UniqueConstraint(Lower('name'), condition=Q(is_deleted=False), name='uq_monitor_boards_name_live',
                                    violation_error_message=_('Another monitoring board already has this name.')),
            models.CheckConstraint(condition=~Q(name=''), name='chk_monitor_boards_name',
                                   violation_error_message=_('Give the board a name.')),
            models.CheckConstraint(condition=Q(default_mode__in=CardMode.values), name='chk_monitor_boards_mode'),
            models.CheckConstraint(
                condition=Q(refresh_seconds__isnull=True) | Q(refresh_seconds__gte=REFRESH_MIN, refresh_seconds__lte=REFRESH_MAX),
                name='chk_monitor_boards_refresh',
                violation_error_message=_('Refresh between 10 and 600 seconds, or leave it empty.')),
            models.CheckConstraint(condition=Q(card_width__in=CardWidth.values), name='chk_monitor_boards_card_width'),
        ]

    def __str__(self):
        return self.name

    @property
    def seconds(self):
        """The interval of its screens: its own, else the system's."""
        return self.refresh_seconds or settings.MONITOR_POLL_SECONDS


class MonitorBoardUnit(models.Model):
    """One card of a board: a unit and how that card is drawn ('' inherits the board's). A row of the board's Units list,
    saved as a whole list (core.crud.RowList), so it has no update or soft-delete columns. There is no position: cards go
    in the farm's one order (site, department, code). A soft-deleted unit keeps its row (a configuration, not history): its
    card is hidden while it is deleted and back when it is restored; saving the board's list drops the row."""

    board = models.ForeignKey(MonitorBoard, on_delete=models.CASCADE, related_name='rows', verbose_name=_('Board'))
    unit = models.ForeignKey(Tank, on_delete=models.CASCADE, related_name='monitor_rows', verbose_name=_('Unit'))
    mode = models.CharField(_('Card'), max_length=10, choices=CardMode.choices, blank=True, default='')
    # This card's template, above every rule (the person arranging this wall); empty: the rules decide. A plain row: it
    # keeps its pointer when the template is deleted (the resolver reads live templates only).
    template = models.ForeignKey('CardTemplate', null=True, blank=True, on_delete=models.SET_NULL, related_name='board_rows',
                                 verbose_name=_('Template'))
    created_at = models.DateTimeField(_('Created at'), auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name='+', verbose_name=_('Created by'))

    class Meta:
        db_table = 'monitor_board_units'
        ordering = ['unit__code']
        verbose_name = _('card of a monitoring board')
        verbose_name_plural = _('cards of a monitoring board')
        constraints = [
            models.UniqueConstraint(fields=['board', 'unit'], name='uq_monitor_board_units_unit',
                                    violation_error_message=_('One card per unit.')),
            models.CheckConstraint(condition=Q(mode__in=['', *CardMode.values]), name='chk_monitor_board_units_mode'),
        ]

    def __str__(self):
        return f'{self.unit.code}: {self.get_mode_display() or "-"}'


# ---- card templates ------------------------------------------------------------------------------------------------
def _json_type(expression):
    return models.Func(expression, function='jsonb_typeof', output_field=models.CharField())


_WIDGETS = KeyTransform('widgets', 'layout')
_IS_ARRAY = Exact(Coalesce(_json_type(_WIDGETS), Value('')), Value('array'))


class CardTemplate(AuditedModel):
    """A named layout of widgets for a monitoring card (monitoring/cards/: the catalogue, the validator). The frame of a
    card (unit, state, reasons, withdrawal, basis, flip link) is not here: a template cannot hide it. Three are built in
    (monitoring/cards/builtin.py): never changed or deleted by any writer (a trigger, migration 0002), copied to make
    one's own.

    What the database holds (a hand edit cannot pass it): a live name, unique in any case; the layout's version one the
    code knows and stamped in the layout too; the layout an object whose widgets are a list of at most 40, in at most 32
    KB; a template not flipping to itself; only the three built-ins built in, never deleted. Everything that needs the
    catalogue (places, sizes, overlaps, bindings, options) is the validator's, once."""

    name = models.CharField(_('Name'), max_length=100)
    description = models.CharField(_('Description'), max_length=300, blank=True, default='')
    is_builtin = models.BooleanField(_('Built in'), default=False, editable=False)
    schema_version = models.PositiveSmallIntegerField(_('Layout version'), default=catalogue.SCHEMA_VERSION,
                                                      editable=False)
    layout = models.JSONField(_('Layout'))
    # The template the card's flip link shows (Simple flips to Detailed and back); empty: no flip link.
    expanded = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL, related_name='expanded_by',
                                 verbose_name=_('Flip link shows'))

    class Meta:
        db_table = 'monitor_card_templates'
        ordering = ['name']
        verbose_name = _('card template')
        verbose_name_plural = _('card templates')
        constraints = [
            models.UniqueConstraint(Lower('name'), condition=Q(is_deleted=False),
                                    name='uq_monitor_card_templates_name_live',
                                    violation_error_message=_('Another card template already has this name.')),
            models.CheckConstraint(condition=~Q(name=''), name='chk_monitor_card_templates_name',
                                   violation_error_message=_('Give the template a name.')),
            models.CheckConstraint(condition=Q(schema_version__gte=1, schema_version__lte=catalogue.SCHEMA_VERSION),
                                   name='chk_monitor_card_templates_schema'),
            models.CheckConstraint(condition=Exact(_json_type(F('layout')), Value('object')),
                                   name='chk_monitor_card_templates_object'),
            models.CheckConstraint(condition=_IS_ARRAY, name='chk_monitor_card_templates_widgets'),
            models.CheckConstraint(
                condition=LessThanOrEqual(Case(When(_IS_ARRAY, then=models.Func(
                    _WIDGETS, function='jsonb_array_length', output_field=models.IntegerField())),
                    default=Value(0)), Value(catalogue.MAX_WIDGETS)),
                name='chk_monitor_card_templates_count'),
            models.CheckConstraint(
                condition=LessThanOrEqual(models.Func(Cast('layout', models.TextField()), function='octet_length',
                                                      output_field=models.IntegerField()), Value(catalogue.MAX_BYTES)),
                name='chk_monitor_card_templates_bytes'),
            models.CheckConstraint(
                condition=Exact(Coalesce(KeyTransform('schema', 'layout'),
                                         models.Func(Value(-1), function='to_jsonb', output_field=models.JSONField())),
                                models.Func(F('schema_version'), function='to_jsonb', output_field=models.JSONField())),
                name='chk_monitor_card_templates_stamp'),
            models.CheckConstraint(condition=~Q(expanded=F('id')), name='chk_monitor_card_templates_expanded',
                                   violation_error_message=_('A template cannot flip to itself.')),
            models.CheckConstraint(condition=Q(is_builtin=False) | Q(id__in=BUILTIN_IDS, is_deleted=False),
                                   name='chk_monitor_card_templates_builtin'),
        ]

    def __str__(self):
        return self.shown_name

    @property
    def shown_name(self):
        """A built-in's name in the person's language (it is a msgid); one's own as it was typed."""
        return gettext(self.name) if self.is_builtin else self.name

    def delete_blockers(self):
        if self.is_builtin:
            return [gettext('A built-in template is never deleted; copy it to make one of your own.')]
        if self.assignments.filter(**GLOBAL_SCOPE).exists():
            return [gettext('Every unit no other rule names gets this template: give the global rule another '
                            'template first.')]
        return []


SCOPES = ('unit', 'system', 'system_type', 'species', 'kind')
GLOBAL_SCOPE = {f'{scope}__isnull': True for scope in SCOPES}


class CardTemplateAssignment(AuditedModel):
    """Which template a unit's card gets: a rule for one scope (a unit, a system, a system type, a species or a unit
    kind) or, with none, every unit (the one global rule). Resolution (monitoring/cards/resolve.py): the board's row,
    then unit, system, system type, species, kind, then the board's default, then the global rule.

    The database holds one scope per rule, one live rule per scope (the global one too: NULLs count as equal), and the
    system type and kind among the farm's. A rule of a deleted unit, system or species stays (DO_NOTHING, as a feeding
    protocol's assignment) and counts again when it is restored; deleting its template deletes it."""

    template = models.ForeignKey(CardTemplate, on_delete=models.CASCADE, related_name='assignments',
                                 verbose_name=_('Template'))
    unit = models.ForeignKey(Tank, null=True, blank=True, on_delete=models.DO_NOTHING, related_name='card_assignments',
                             verbose_name=_('Unit'))
    system = models.ForeignKey(System, null=True, blank=True, on_delete=models.DO_NOTHING,
                               related_name='card_assignments', verbose_name=_('System'))
    system_type = models.CharField(_('System type'), max_length=20, null=True, blank=True, choices=System.Type.choices)
    species = models.ForeignKey(Species, null=True, blank=True, on_delete=models.DO_NOTHING,
                                related_name='card_assignments', verbose_name=_('Species'))
    kind = models.CharField(_('Unit kind'), max_length=10, null=True, blank=True, choices=Tank.Kind.choices)

    class Meta:
        db_table = 'monitor_card_assignments'
        ordering = ['created_at']
        verbose_name = _('card template rule')
        verbose_name_plural = _('card template rules')
        constraints = [
            models.CheckConstraint(
                condition=LessThanOrEqual(models.Func(*(F(scope) for scope in SCOPES), function='num_nonnulls',
                                                      output_field=models.IntegerField()), Value(1)),
                name='chk_monitor_card_assignments_one_scope',
                violation_error_message=_('A rule is for one unit, system, system type, species or kind, or for '
                                          'every unit.')),
            models.UniqueConstraint(fields=list(SCOPES), condition=Q(is_deleted=False), nulls_distinct=False,
                                    name='uq_monitor_card_assignments_scope',
                                    violation_error_message=_('There is already a rule for this.')),
            models.CheckConstraint(condition=Q(system_type__isnull=True) | Q(system_type__in=System.Type.values),
                                   name='chk_monitor_card_assignments_system_type'),
            models.CheckConstraint(condition=Q(kind__isnull=True) | Q(kind__in=Tank.Kind.values),
                                   name='chk_monitor_card_assignments_kind'),
        ]

    def __str__(self):
        return f'{self.scope_label}: {self.template}'

    @property
    def is_global(self):
        return (self.unit_id, self.system_id, self.system_type, self.species_id, self.kind) == (None,) * 5

    @property
    def scope_label(self):
        """What the rule is for, in the person's language."""
        if self.unit_id:
            return self.unit.code
        if self.system_id:
            return str(self.system)
        if self.system_type:
            return str(self.get_system_type_display())
        if self.species_id:
            return str(self.species)
        if self.kind:
            return str(self.get_kind_display())
        return gettext('Every unit')

    def delete_blockers(self):
        if self.is_global:
            return [gettext('The global rule is never deleted: every unit must get a template. Change its template '
                            'instead.')]
        return []
