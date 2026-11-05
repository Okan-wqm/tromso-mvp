from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.db.models import F, Q
from django.utils.translation import gettext_lazy as _

from core.fields import ChoiceArrayField
from core.models import CODE, CODE_MESSAGE, AuditedModel, CodedMixin
from farm.models import Site

MAX_BREAK, MAX_GRACE, TONES = 240, 120, 8


class Weekday(models.IntegerChoices):
    """Python's weekday numbers, Monday 0 (a week is the ISO week: it starts on Monday, no setting)."""
    MONDAY = 0, _('Monday')
    TUESDAY = 1, _('Tuesday')
    WEDNESDAY = 2, _('Wednesday')
    THURSDAY = 3, _('Thursday')
    FRIDAY = 4, _('Friday')
    SATURDAY = 5, _('Saturday')
    SUNDAY = 6, _('Sunday')


def span_minutes(starts_at, ends_at):
    """The minutes between two wall-clock times; an end at or before the start means the next day. (A shift is a
    length, not a pair of instants: the instants come from the day and the site's zone, hr.clock.)"""
    start = starts_at.hour * 60 + starts_at.minute
    end = ends_at.hour * 60 + ends_at.minute
    return (end - start) % (24 * 60) or 24 * 60


class Shift(CodedMixin, AuditedModel):
    """A shift pattern the roster uses: a name, a code, the wall-clock start and end (an end at or before the start is
    the next day), an unpaid break, a grace in minutes before a late arrival counts, and a tone 1-8 (a CSS class: no
    colour value is ever stored). Owner data: nothing is seeded."""

    class Status(models.TextChoices):
        ACTIVE = 'active', _('Active')
        INACTIVE = 'inactive', _('Inactive')

    name = models.CharField(_('Name'), max_length=50)
    code = models.CharField(_('Code'), max_length=20, validators=[RegexValidator(CODE, CODE_MESSAGE)])
    starts_at = models.TimeField(_('Starts at'))
    ends_at = models.TimeField(_('Ends at'))
    break_minutes = models.PositiveSmallIntegerField(_('Break (minutes)'), default=0,
                                                     validators=[MaxValueValidator(MAX_BREAK)])
    grace_minutes = models.PositiveSmallIntegerField(_('Grace (minutes)'), default=0,
                                                     validators=[MaxValueValidator(MAX_GRACE)])
    tone = models.PositiveSmallIntegerField(_('Tone'), default=1,
                                            validators=[MinValueValidator(1), MaxValueValidator(TONES)])
    status = models.CharField(_('Status'), max_length=10, choices=Status.choices, default=Status.ACTIVE)

    class Meta:
        db_table = 'shifts'
        ordering = ['starts_at', 'code']
        verbose_name = _('shift')
        verbose_name_plural = _('shifts')
        constraints = [
            models.UniqueConstraint(fields=['code'], condition=Q(is_deleted=False), name='uq_shifts_code_live',
                                    violation_error_message=_('Another shift already uses this code.')),
            models.CheckConstraint(condition=Q(code__regex=CODE), name='chk_shifts_code',
                                   violation_error_message=CODE_MESSAGE),
            models.CheckConstraint(condition=~Q(starts_at=F('ends_at')), name='chk_shifts_span',
                                   violation_error_message=_('A shift cannot start and end at the same time.')),
            models.CheckConstraint(condition=Q(break_minutes__gte=0, break_minutes__lte=MAX_BREAK),
                                   name='chk_shifts_break',
                                   violation_error_message=_('The break is between 0 and 240 minutes.')),
            models.CheckConstraint(condition=Q(grace_minutes__gte=0, grace_minutes__lte=MAX_GRACE),
                                   name='chk_shifts_grace',
                                   violation_error_message=_('The grace is between 0 and 120 minutes.')),
            models.CheckConstraint(condition=Q(tone__gte=1, tone__lte=TONES), name='chk_shifts_tone',
                                   violation_error_message=_('The tone is between 1 and 8.')),
            models.CheckConstraint(condition=Q(status__in=['active', 'inactive']), name='chk_shifts_status'),
        ]

    @property
    def span_minutes(self):
        return span_minutes(self.starts_at, self.ends_at)

    @property
    def paid_minutes(self):
        """The planned minutes without the break (the instants' length changes on a day the clocks change: hr.clock)."""
        return self.span_minutes - self.break_minutes

    def clean(self):
        super().clean()
        if self.starts_at and self.ends_at and self.break_minutes is not None \
                and self.break_minutes >= span_minutes(self.starts_at, self.ends_at):
            from django.core.exceptions import ValidationError
            raise ValidationError({'break_minutes': _('The break must be shorter than the shift.')})


class Holiday(AuditedModel):
    """A day that is not a working day: for every site (no site) or for one. Typed in by HR, never seeded (the
    country's days are the owner's data). A leave request is not charged for a holiday (hr.leave)."""

    day = models.DateField(_('Day'))
    name = models.CharField(_('Name'), max_length=100)
    site = models.ForeignKey(Site, null=True, blank=True, on_delete=models.PROTECT, related_name='holidays',
                             verbose_name=_('Site'))

    class Meta:
        db_table = 'holidays'
        ordering = ['day', 'name']
        verbose_name = _('holiday')
        verbose_name_plural = _('holidays')
        constraints = [
            # One holiday a day for every site and one for each site; the missing site counts as one value.
            models.UniqueConstraint(fields=['day', 'site'], condition=Q(is_deleted=False), nulls_distinct=False,
                                    name='uq_holidays_day_site_live',
                                    violation_error_message=_('This day is already a holiday for this site.')),
        ]
        indexes = [models.Index(fields=['day'])]

    def __str__(self):
        return f'{self.name} ({self.day})'


def default_weekdays():
    return [0, 1, 2, 3, 4]


class RestRule(models.TextChoices):
    WARN = 'warn', _('Warn')
    BLOCK = 'block', _('Block')


class SchedulingSettings(AuditedModel):
    """The scheduling limits and defaults, one row for the company (a database check keeps it one). Each setting has
    exactly one reader (hr.rules, hr.leave, hr.read); a default is a labelled default, not the law: none of the statutory
    figures is verified, so none is a constraint here. A person may be stricter than the law, never asked to be less."""

    singleton = models.BooleanField(default=True, editable=False)
    standard_week_minutes = models.PositiveIntegerField(_('Standard week (minutes)'), default=2400,
                                                        validators=[MaxValueValidator(10080)])
    min_rest_minutes = models.PositiveIntegerField(_('Minimum rest between shifts (minutes)'), default=660,
                                                   validators=[MaxValueValidator(1440)])
    max_consecutive_days = models.PositiveSmallIntegerField(
        _('Most working days in a row'), default=6, validators=[MinValueValidator(1), MaxValueValidator(14)])
    rest_rule = models.CharField(_('A short rest, a long week or too many days in a row'), max_length=5,
                                 choices=RestRule.choices, default=RestRule.WARN)
    working_weekdays = ChoiceArrayField(models.PositiveSmallIntegerField(choices=Weekday.choices),
                                        default=default_weekdays, verbose_name=_('Working weekdays'))
    punch_window_minutes = models.PositiveSmallIntegerField(
        _('Punch window (minutes)'), default=120, validators=[MaxValueValidator(720)])
    absent_after_minutes = models.PositiveSmallIntegerField(
        _('Absent after (minutes)'), default=30, validators=[MaxValueValidator(240)])

    class Meta:
        db_table = 'scheduling_settings'
        verbose_name = _('scheduling settings')
        verbose_name_plural = _('scheduling settings')
        constraints = [
            models.UniqueConstraint(fields=['singleton'], name='uq_scheduling_settings_singleton'),
            models.CheckConstraint(condition=Q(singleton=True), name='chk_scheduling_settings_singleton'),
            models.CheckConstraint(condition=Q(standard_week_minutes__lte=10080), name='chk_scheduling_week'),
            models.CheckConstraint(condition=Q(min_rest_minutes__lte=1440), name='chk_scheduling_rest'),
            models.CheckConstraint(condition=Q(max_consecutive_days__gte=1, max_consecutive_days__lte=14),
                                   name='chk_scheduling_consecutive'),
            models.CheckConstraint(condition=Q(rest_rule__in=['warn', 'block']), name='chk_scheduling_rule'),
            models.CheckConstraint(condition=Q(working_weekdays__contained_by=Weekday.values)
                                   & Q(working_weekdays__len__gt=0), name='chk_scheduling_weekdays'),
            models.CheckConstraint(condition=Q(punch_window_minutes__lte=720), name='chk_scheduling_punch_window'),
            models.CheckConstraint(condition=Q(absent_after_minutes__lte=240), name='chk_scheduling_absent_after'),
        ]

    def __str__(self):
        return str(_('Scheduling settings'))

    @property
    def weekday_labels(self):
        """The working weekdays by name, for the page."""
        labels = dict(Weekday.choices)
        return [labels[day] for day in self.working_weekdays]

    @classmethod
    def get(cls):
        """The one row (made by the migration; made again here if a restore left none)."""
        return cls.objects.first() or cls.objects.create()
