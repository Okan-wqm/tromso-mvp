from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import DateTimeRangeField, RangeBoundary, RangeOperators
from django.db import models
from django.db.models import F, Func, Q
from django.utils.translation import gettext_lazy as _

from core.models import AuditedModel
from farm.models import Equipment, SamplingPoint, System
from farm.models.water_point import live_owner

from .channel import Channel

TARGETS = ('point', 'system', 'equipment')


class Role(models.TextChoices):
    PRIMARY = 'primary', _('Primary')
    BACKUP = 'backup', _('Backup')


class TsTzRange(Func):
    """tstzrange(valid_from, valid_to, '[)'): the time a binding holds, its end open when it has none."""
    function = 'TSTZRANGE'
    output_field = DateTimeRangeField()


def _one_target():
    named = {name: Q(**{f'{name}__isnull': False}) for name in TARGETS}
    condition = Q()
    for chosen in TARGETS:
        branch = named[chosen]
        for other in TARGETS:
            if other != chosen:
                branch &= ~named[other]
        condition |= branch
    return condition


def place_site(prefix=''):
    """The site of a binding's place (`prefix`: the path to the binding, e.g. 'binding__'), as the database works it out:
    migration 0007's `sensors_place_site`, the one definition (NULL for a department without a site)."""
    return Func(F(f'{prefix}point_id'), F(f'{prefix}system_id'), F(f'{prefix}equipment_id'), function='sensors_place_site',
                output_field=models.UUIDField())


class BindingQuerySet(models.QuerySet):
    def visible(self):
        """The live bindings of live channels whose target is live: a deleted point (or its deleted owner), system or
        piece of equipment hides its bindings, which come back with it."""
        return self.filter(
            Q(point__isnull=True) | (Q(point__is_deleted=False) & live_owner('point__')),
            Q(system__isnull=True) | Q(system__is_deleted=False),
            Q(equipment__isnull=True) | Q(equipment__is_deleted=False),
            channel__is_deleted=False)

    def at(self, moment):
        """The bindings that hold at `moment`: from `valid_from`, up to but not including `valid_to`."""
        return self.filter(Q(valid_to__isnull=True) | Q(valid_to__gt=moment), valid_from__lte=moment)


class BindingManager(models.Manager.from_queryset(BindingQuerySet)):
    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=False)


class Binding(AuditedModel):
    """Where a channel's values belong over a time range: a sampling point or a system for a water value (a system's own
    water as a whole, owner rule A1), a piece of equipment or a system for a process value. Primary or backup: per target
    and quantity at most one of each at a time. History is never edited: a sensor moved to another tank closes its
    binding and opens a new one (sensors/bindings.py `move`), so its earlier values stay with the tank they were taken
    in. A deleted target keeps its bindings, out of sight, and they come back when it is restored."""

    Role = Role

    channel = models.ForeignKey(Channel, on_delete=models.CASCADE, related_name='bindings', verbose_name=_('Channel'))
    point = models.ForeignKey(SamplingPoint, null=True, blank=True, on_delete=models.DO_NOTHING,
                              related_name='sensor_bindings', verbose_name=_('Sampling point'))
    system = models.ForeignKey(System, null=True, blank=True, on_delete=models.DO_NOTHING,
                               related_name='sensor_bindings', verbose_name=_('System'))
    equipment = models.ForeignKey(Equipment, null=True, blank=True, on_delete=models.DO_NOTHING,
                                  related_name='sensor_bindings', verbose_name=_('Equipment'))
    role = models.CharField(_('Role'), max_length=10, choices=Role.choices, default=Role.PRIMARY)
    valid_from = models.DateTimeField(_('From'))
    valid_to = models.DateTimeField(_('Until'), null=True, blank=True)
    note = models.CharField(_('Note'), max_length=300, blank=True)

    objects = BindingManager()
    all_objects = models.Manager.from_queryset(BindingQuerySet)()

    kept_note = _('They stay, out of sight while it is deleted, and come back when it is restored: the values the sensor '
                  'measured there keep belonging there.')

    class Meta:
        db_table = 'sensors_binding'
        ordering = ['-valid_from']
        verbose_name = _('channel binding')
        verbose_name_plural = _('channel bindings')
        constraints = [
            models.CheckConstraint(condition=_one_target(), name='chk_sensors_binding_one_target',
                                   violation_error_message=_('A binding is to one sampling point, one system or one '
                                                             'piece of equipment.')),
            models.CheckConstraint(condition=Q(valid_to__isnull=True) | Q(valid_to__gt=F('valid_from')),
                                   name='chk_sensors_binding_period',
                                   violation_error_message=_('The end comes after the start.')),
            models.CheckConstraint(condition=Q(role__in=Role.values), name='chk_sensors_binding_role'),
            ExclusionConstraint(
                name='ex_sensors_binding_channel_period',
                expressions=[(F('channel'), RangeOperators.EQUAL),
                             (TsTzRange('valid_from', 'valid_to', RangeBoundary()), RangeOperators.OVERLAPS)],
                condition=Q(is_deleted=False),
                violation_error_message=_('The channel is bound elsewhere at that time: a channel is in one place at a '
                                          'time.')),
        ]
        indexes = [models.Index(fields=['point', 'valid_from'], name='sensors_binding_point_idx'),
                   models.Index(fields=['system', 'valid_from'], name='sensors_binding_system_idx'),
                   models.Index(fields=['equipment', 'valid_from'], name='sensors_binding_equipment_idx')]

    def __str__(self):
        return f'{self.channel}: {self.target}'

    @property
    def target(self):
        return self.point or self.system or self.equipment

    def took(self, moment):
        """Whether a value measured at `moment` is this place's: taken while the binding held (a moved probe's value
        from its previous place, or from while it was out of the water, is not). The one rule the latest values and
        the alarms read a channel's state by."""
        return moment is not None and self.valid_from <= moment and (self.valid_to is None or moment < self.valid_to)

    @property
    def target_kind(self):
        return next((name for name in TARGETS if getattr(self, f'{name}_id')), '')
