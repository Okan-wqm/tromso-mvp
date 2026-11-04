"""The only thing the monitoring cards store: a named, shared wall board, the units on it and how each is drawn. A figure, a
state, a token or a chart is never stored: a card is worked out from the other apps' records every time it is asked for
(monitoring/read.py). Window places are kept per device in the browser, not here.

Rules the database can hold are constraints (a board's name unique among live boards, case-insensitively, and not blank;
the modes and the refresh seconds in their ranges; one card per unit per board); the form mirrors them for friendly
messages. That a board holds only live units is not a row fact (liveness is soft-delete state), so it is the form's
choices and the read's live join."""
from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _

from core.models import AuditedModel
from farm.models import Tank

SIMPLE, DETAILED = 'simple', 'detailed'
REFRESH_MIN, REFRESH_MAX = 10, 600


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
