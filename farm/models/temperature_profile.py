"""Temperature profiles and where they apply (Operations › Feeding › Temperature profiles and Profile assignments; owner
decisions 15–17 of 2026-11-26).

A profile is reference data for one species, like a feeding protocol: the water temperature the fish are expected to
be kept at as they grow, as points of weight (g) → temperature (°C). Between two points the temperature follows the
profile's rule (smooth: read in between; step: the point's value from its weight on), constant before the first point
and after the last (farm/feeding/growth.py: the same pure functions as a protocol's bands). It is read by the production
plan for the days ahead only: the temperature of a day ahead is the profile's at the fish's projected weight that day;
the past keeps the temperatures measured.

A profile is assigned as a protocol is (farm/models/assignment.py: the same three targets, the same rules, the same
resolver), and once assigned its points, species and rule are fixed (Q3): a change is made on a copy."""
from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _

from core.models import AuditedModel

from ..water import parameters
from .assignment import Assignable, BetweenBands, ProtocolStatus, TargetedAssignment, assignment_constraints
from .feed import MAX_WEIGHT_G
from .species import Species
from .stock import Batch
from .tank import Tank

TEMPERATURE = parameters.get(parameters.TEMPERATURE)
MAX_POINTS = 30


class TemperatureProfile(Assignable, AuditedModel):
    """The water temperature over the fish's weight for one species: its points (TemperatureProfilePoint) and how the
    temperature is read between two of them. Draft, active, retired as a feeding protocol."""

    Status = ProtocolStatus
    FIXED = ('species', 'temperature_between')
    NEEDS_TABLE = _('Give its points first: a profile without them cannot be active.')
    FIXED_MESSAGE = _('Fixed: the profile is assigned. Duplicate it to change it.')

    name = models.CharField(_('Name'), max_length=100)
    species = models.ForeignKey(Species, on_delete=models.PROTECT, related_name='temperature_profiles',
                                limit_choices_to={'is_deleted': False}, verbose_name=_('Species'))
    status = models.CharField(_('Status'), max_length=10, choices=ProtocolStatus.choices,
                              default=ProtocolStatus.DRAFT)
    temperature_between = models.CharField(_('Temperature between points'), max_length=6,
                                           choices=BetweenBands.choices, default=BetweenBands.SMOOTH)
    notes = models.CharField(_('Notes'), max_length=2000, blank=True)

    class Meta:
        db_table = 'temperature_profiles'
        ordering = ['name']
        verbose_name = _('temperature profile')
        verbose_name_plural = _('temperature profiles')
        constraints = [
            models.UniqueConstraint(
                Lower('name'), condition=Q(is_deleted=False), name='uq_temperature_profiles_name_live',
                violation_error_message=_('Another temperature profile already has this name.')),
            models.CheckConstraint(condition=Q(status__in=ProtocolStatus.values),
                                   name='chk_temperature_profiles_status'),
            models.CheckConstraint(condition=Q(temperature_between__in=BetweenBands.values),
                                   name='chk_temperature_profiles_between'),
        ]

    def __str__(self):
        return self.name

    def has_table(self):
        return self.points.exists()


class TemperatureProfilePoint(models.Model):
    """A point of a profile: fish of this weight (g) are expected in water of this temperature (°C). Saved as the
    profile's list (core.crud.RowList), so these rows have no update or soft-delete columns; the change is logged on the
    profile."""

    profile = models.ForeignKey(TemperatureProfile, on_delete=models.CASCADE, related_name='points',
                                verbose_name=_('Temperature profile'))
    weight_g = models.DecimalField(_('Fish weight (g)'), max_digits=10, decimal_places=2,
                                   validators=[MinValueValidator(0), MaxValueValidator(MAX_WEIGHT_G)])
    temperature_c = models.DecimalField(_('Temperature (°C)'), max_digits=3, decimal_places=1,
                                        validators=[MinValueValidator(TEMPERATURE.low),
                                                    MaxValueValidator(TEMPERATURE.high)])
    created_at = models.DateTimeField(_('Created at'), auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name='+', verbose_name=_('Created by'))

    class Meta:
        db_table = 'temperature_profile_points'
        ordering = ['profile', 'weight_g']
        verbose_name = _('temperature profile point')
        verbose_name_plural = _('temperature profile points')
        constraints = [
            models.CheckConstraint(condition=Q(weight_g__gte=0, weight_g__lte=MAX_WEIGHT_G),
                                   name='chk_temperature_profile_points_weight'),
            models.CheckConstraint(condition=Q(temperature_c__gte=TEMPERATURE.low,
                                               temperature_c__lte=TEMPERATURE.high),
                                   name='chk_temperature_profile_points_temperature'),
            models.UniqueConstraint(fields=['profile', 'weight_g'], name='uq_temperature_profile_points_weight',
                                    violation_error_message=_('Each weight is a point once.')),
        ]

    def __str__(self):
        return f'{self.weight_g.normalize():f} g: {self.temperature_c.normalize():f} °C'


class TemperatureProfileAssignment(TargetedAssignment):
    """A temperature profile in force for a unit, a whole batch or a batch in one unit, from a day (the rules of
    farm/models/assignment.py, shared with the protocols' rows)."""

    SUBJECT = 'profile'
    ONLY_ACTIVE = _('Only an active temperature profile can be assigned; this one is %(status)s.')
    OTHER_SPECIES = _('%(batch)s is %(species)s; the profile is for %(protocol_species)s.')
    STARTED = _('It has started: set its last day instead. The days it planned keep their profile.')

    profile = models.ForeignKey(TemperatureProfile, on_delete=models.PROTECT, related_name='assignments',
                                verbose_name=_('Temperature profile'))
    unit = models.ForeignKey(Tank, null=True, blank=True, on_delete=models.DO_NOTHING,
                             related_name='profile_assignments', verbose_name=_('Unit'))
    batch = models.ForeignKey(Batch, null=True, blank=True, on_delete=models.DO_NOTHING,
                              related_name='profile_assignments', verbose_name=_('Batch'))

    class Meta:
        db_table = 'temperature_profile_assignments'
        ordering = ['-valid_from', '-created_at', 'group_id']
        verbose_name = _('profile assignment')
        verbose_name_plural = _('profile assignments')
        constraints = assignment_constraints(
            'temperature_profile_assignments',
            _('Another temperature profile is assigned to this unit on some of these days.'),
            _('Another temperature profile is assigned to this batch on some of these days.'),
            _('Another temperature profile is assigned to this batch in this unit on some of these days.'))
