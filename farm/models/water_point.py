"""Sampling points: where in the farm's water a sample is taken (Setup › Facility structure › Sampling points).

A sample says exactly where it was taken so that a mass balance can later run on it: concentration × flow
at every inlet and outlet of a unit, a loop or a piece of equipment. The point is that "where": a named
place on ONE owner, a unit (a tank, pond or cage), a system (its loop) or a piece of equipment (a
biofilter, a degasser, a drum filter, a pump), with a kind from a fixed list in this file, because the
mass-balance code must know what each kind means: the kind says whether the point sees the stream
entering its owner, the water inside it or the stream leaving it (`flow_role`, the one place that says so).

What is stored is the structure only (README, "Preparing for a mass balance"): the owner, the kind, a
design or last-known flow for the points on a stream, and for an outlet the share of the owner's outflow
that leaves there (a tank's side outlet takes 90 %, its bottom drain 10 %). Not built, and not stored
here: which outlet feeds which inlet, measured flows, the sensor channels assigned to a point.

The rules that span rows cannot be a database check, so they are in `clean()` and the services: an owner's
active outlet shares add up to at most 100 % (and are reported when they do not add up to 100), and a kind
fits its owner (a cage has no bottom drain). Everything one row can say is a database check: exactly one
owner, a kind from the list, the depth only for a depth point, the flow only on a stream, the share only on
an outlet, a name that is not empty, a name unique among the owner's live points, and one active middle
point per owner (the point that stands for "the owner's water": farm/water/read.py)."""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _, ngettext

from core.models import ActiveManager, AuditedModel

from .equipment import Equipment
from .site import zone_of
from .system import System
from .tank import Tank


# ---- what a point is ---------------------------------------------------------------------------------------
class PointKind(models.TextChoices):
    """Where at its owner the water is taken, from a fixed list: the flow role of each is `FLOW_ROLE`."""
    INLET = 'inlet', _('Inlet')
    MIDDLE = 'middle', _('Middle')
    DEPTH = 'depth', _('Depth point')
    OUTLET = 'outlet', _('Outlet')
    SIDE_OUTLET = 'side_outlet', _('Side outlet')
    BOTTOM_DRAIN = 'bottom_drain', _('Bottom drain')


class FlowRole(models.TextChoices):
    """What a point sees of the owner's water: the stream entering it, the water within it, or the stream
    leaving it. A mass balance reads concentration × flow at the points of the first and the last."""
    IN = 'in', _('Stream in')
    WITHIN = 'within', _('Within')
    OUT = 'out', _('Stream out')


# The one place that says what each kind means for the flow; every reader asks `flow_role`.
FLOW_ROLE = {
    PointKind.INLET: FlowRole.IN,
    PointKind.MIDDLE: FlowRole.WITHIN,
    PointKind.DEPTH: FlowRole.WITHIN,
    PointKind.OUTLET: FlowRole.OUT,
    PointKind.SIDE_OUTLET: FlowRole.OUT,
    PointKind.BOTTOM_DRAIN: FlowRole.OUT,
}


def flow_role(kind):
    """The FlowRole of a point kind."""
    return FlowRole(FLOW_ROLE[PointKind(kind)])


def kinds_with(*roles):
    """The kinds whose flow role is one of `roles`, in the list's order."""
    return [kind.value for kind in PointKind if FLOW_ROLE[kind] in roles]


STREAM_KINDS = kinds_with(FlowRole.IN, FlowRole.OUT)    # a flow can be stated at these
OUTLET_KINDS = kinds_with(FlowRole.OUT)                  # these can take a share of the owner's outflow

# The owners a point can be on, as the field of the point that holds each.
UNIT, SYSTEM, EQUIPMENT = 'unit', 'system', 'equipment'
OWNER_FIELDS = (UNIT, SYSTEM, EQUIPMENT)

# The kinds each owner can have: a unit by what it is (a tank has a sidewall and a bottom drain, a pond an
# outlet, a cage only its water and the depths in it), a loop its sump, its make-up water and its discharge, a
# piece of equipment its inlet, its inside and its outlets (a drum filter has two: the clean water and the
# backwash).
OWNER_KINDS = {
    Tank.Kind.TANK: [PointKind.INLET, PointKind.MIDDLE, PointKind.DEPTH, PointKind.OUTLET, PointKind.SIDE_OUTLET,
                     PointKind.BOTTOM_DRAIN],
    Tank.Kind.POND: [PointKind.INLET, PointKind.MIDDLE, PointKind.DEPTH, PointKind.OUTLET],
    Tank.Kind.CAGE: [PointKind.MIDDLE, PointKind.DEPTH],
    SYSTEM: [PointKind.INLET, PointKind.MIDDLE, PointKind.OUTLET],
    EQUIPMENT: [PointKind.INLET, PointKind.MIDDLE, PointKind.OUTLET],
}
# What the model allows for a stored flow: a stream of up to 100,000 m³/h (28 m³/s), more than any farm's.
MAX_FLOW_M3_H = 100000
MAX_DEPTH_M = 200


def kinds_for(owner):
    """The kinds of point `owner` (a unit, a system or a piece of equipment) can have, in the list's order."""
    if isinstance(owner, Tank):
        return [PointKind(kind) for kind in OWNER_KINDS[owner.kind]]
    return [PointKind(kind) for kind in OWNER_KINDS[SYSTEM if isinstance(owner, System) else EQUIPMENT]]


def owner_type_of(owner):
    """'unit', 'system' or 'equipment'."""
    return UNIT if isinstance(owner, Tank) else SYSTEM if isinstance(owner, System) else EQUIPMENT


def site_of(place):
    """The site of a unit or a piece of equipment (through its production department, which may have none), of
    a system, or of a sampling point (its owner's)."""
    if isinstance(place, SamplingPoint):
        place = place.owner
    return place.site if isinstance(place, System) else place.production_department.site


def local_time(moment, place):
    """A moment on the clock of the place's site (farm.models.site.zone_of)."""
    return moment.astimezone(zone_of(site_of(place)))


# ---- which points are visible ------------------------------------------------------------------------------
def live_owner(prefix=''):
    """The condition "the owner of this point is not deleted", for the point itself or, with a prefix
    ('point__'), for the point of a sample. A deleted owner keeps its points, out of sight, and they come back
    with it when it is restored (core.softdelete: the link keeps them, DO_NOTHING; restoring a record brings back
    only that record, so points deleted with their owner would never return)."""
    condition = Q()
    for owner in OWNER_FIELDS:
        condition &= Q(**{f'{prefix}{owner}__isnull': True}) | Q(**{f'{prefix}{owner}__is_deleted': False})
    return condition


class PointQuerySet(models.QuerySet):
    def with_owners(self):
        """With the owners and their sites, for what shows a point's label, site or clock."""
        return self.select_related('unit__production_department__site', 'system__site',
                                   'equipment__production_department__site')


class PointManager(ActiveManager.from_queryset(PointQuerySet)):
    """Live points of live owners."""

    def get_queryset(self):
        return super().get_queryset().filter(live_owner())


def _checks():
    named = {owner: Q(**{f'{owner}__isnull': False}) for owner in OWNER_FIELDS}
    one_owner = Q()
    for chosen in OWNER_FIELDS:
        branch = named[chosen]
        for other in OWNER_FIELDS:
            if other != chosen:
                branch &= ~named[other]
        one_owner |= branch
    return [
        models.CheckConstraint(condition=one_owner, name='chk_water_sampling_points_one_owner',
                               violation_error_message=_('A point is on one unit, one system or one piece of '
                                                         'equipment.')),
        models.CheckConstraint(condition=Q(kind__in=PointKind.values), name='chk_water_sampling_points_kind'),
        models.CheckConstraint(condition=~Q(name=''), name='chk_water_sampling_points_name',
                               violation_error_message=_('Give the point a name.')),
        models.CheckConstraint(
            condition=(Q(kind=PointKind.DEPTH, depth_m__isnull=False, depth_m__gte=0, depth_m__lte=MAX_DEPTH_M)
                       | (~Q(kind=PointKind.DEPTH) & Q(depth_m__isnull=True))),
            name='chk_water_sampling_points_depth',
            violation_error_message=_('A depth point has a depth, and no other point does.')),
        models.CheckConstraint(
            condition=Q(flow_m3_h__isnull=True) | (Q(kind__in=STREAM_KINDS) & Q(flow_m3_h__gte=0,
                                                                                   flow_m3_h__lte=MAX_FLOW_M3_H)),
            name='chk_water_sampling_points_flow',
            violation_error_message=_('A flow can be stated for an inlet or an outlet only.')),
        models.CheckConstraint(
            condition=Q(flow_share_pct__isnull=True) | (Q(kind__in=OUTLET_KINDS) & Q(flow_share_pct__gte=0,
                                                                                       flow_share_pct__lte=100)),
            name='chk_water_sampling_points_share',
            violation_error_message=_('A share of the outflow, from 0 to 100 %, can be stated for an outlet only.')),
    ]


def _uniques():
    """A name unique among an owner's live points whatever its case, and one active middle point per owner."""
    constraints = []
    for owner in OWNER_FIELDS:
        constraints += [
            models.UniqueConstraint(
                models.F(owner), Lower('name'), condition=Q(is_deleted=False, **{f'{owner}__isnull': False}),
                name=f'uq_water_sampling_points_{owner}_name',
                violation_error_message=_('This owner already has a point with this name.')),
            models.UniqueConstraint(
                models.F(owner), condition=Q(is_deleted=False, is_active=True, kind=PointKind.MIDDLE,
                                             **{f'{owner}__isnull': False}),
                name=f'uq_water_sampling_points_{owner}_middle',
                violation_error_message=_('This owner already has an active middle point: it stands for its water.')),
        ]
    return constraints


class SamplingPoint(AuditedModel):
    """A place a water sample is taken: a named point of one unit, one system's loop or one piece of equipment,
    of a kind that says whether it sees the stream in, the water within or the stream out (Setup › Facility
    structure › Sampling points). New table; the source's measurement point was the owner itself, with a
    position and a depth that only its sensor bindings kept (WQ-40).

    `flow_m3_h` is the design or last-known flow of the stream at an inlet or an outlet and `flow_share_pct` the
    share of the owner's outflow that leaves at an outlet (a side outlet 90, a bottom drain 10); neither is
    measured here. The owner's active outlet shares add up to at most 100, checked on save and reported when
    they do not add up to 100. A point that has samples is never deleted (they stay in the history): it is made
    inactive, which keeps its samples and takes no new ones. Its samples are the unit's, the loop's or the
    equipment's, found through the point (farm/water/read.py)."""

    Kind, Role = PointKind, FlowRole

    # A deleted owner keeps its points, out of sight (PointManager); see live_owner.
    unit = models.ForeignKey(Tank, null=True, blank=True, on_delete=models.DO_NOTHING, related_name='sampling_points',
                             verbose_name=_('Unit'))
    system = models.ForeignKey(System, null=True, blank=True, on_delete=models.DO_NOTHING,
                               related_name='sampling_points', verbose_name=_('System'))
    equipment = models.ForeignKey(Equipment, null=True, blank=True, on_delete=models.DO_NOTHING,
                                  related_name='sampling_points', verbose_name=_('Equipment'))
    name = models.CharField(_('Name'), max_length=100)
    kind = models.CharField(_('Kind'), max_length=20, choices=PointKind.choices)
    depth_m = models.DecimalField(_('Depth (m)'), max_digits=4, decimal_places=1, null=True, blank=True,
                                  validators=[MinValueValidator(0), MaxValueValidator(MAX_DEPTH_M)])
    flow_m3_h = models.DecimalField(_('Flow (m³/h)'), max_digits=8, decimal_places=2, null=True, blank=True,
                                    validators=[MinValueValidator(0), MaxValueValidator(MAX_FLOW_M3_H)])
    flow_share_pct = models.DecimalField(_('Share of the outflow (%)'), max_digits=5, decimal_places=2, null=True,
                                         blank=True, validators=[MinValueValidator(0), MaxValueValidator(100)])
    is_active = models.BooleanField(_('Active'), default=True)
    description = models.CharField(_('Description'), max_length=300, blank=True)

    objects = PointManager()
    all_objects = models.Manager.from_queryset(PointQuerySet)()

    class Meta:
        db_table = 'water_sampling_points'
        ordering = ['name']
        verbose_name = _('sampling point')
        verbose_name_plural = _('sampling points')
        constraints = [*_checks(), *_uniques()]

    def __str__(self):
        return f'{self.owner.code} › {self.name}'

    # ---- where it is ------------------------------------------------------------------------------------
    @property
    def owner(self):
        """The unit, the system or the piece of equipment it is on."""
        return self.unit or self.system or self.equipment

    @property
    def owner_type(self):
        """'unit', 'system' or 'equipment'; None before an owner is set."""
        return next((name for name in OWNER_FIELDS if getattr(self, f'{name}_id')), None)

    @property
    def site(self):
        return site_of(self)

    @property
    def role(self):
        return flow_role(self.kind)

    # ---- the rules that span rows or records ---------------------------------------------------------------
    def other_shares(self):
        """What the owner's other live active outlets take of its outflow, in %: the sum of their shares."""
        if self.owner_type is None:
            return Decimal(0)
        others = type(self).objects.filter(**{self.owner_type: getattr(self, self.owner_type)}, is_active=True,
                                           flow_share_pct__isnull=False).exclude(pk=self.pk)
        return others.aggregate(total=models.Sum('flow_share_pct'))['total'] or Decimal(0)

    def tidy(self):
        """Empties what the kind does not use, as a unit's kind-dependent fields are (Tank.tidy): the depth of a point
        that is not a depth point, the flow of one that is on no stream, the share of one that is not an outlet.
        `clean` does it, so a form that drops those fields for a kind never stores what an earlier kind had."""
        if self.kind != PointKind.DEPTH:
            self.depth_m = None
        if self.kind not in STREAM_KINDS:
            self.flow_m3_h = None
        if self.kind not in OUTLET_KINDS:
            self.flow_share_pct = None

    def clean(self):
        super().clean()
        self.tidy()
        errors = {}
        owner = self.owner
        if self.kind in PointKind.values and owner is not None and PointKind(self.kind) not in kinds_for(owner):
            errors['kind'] = ValidationError(
                _('%(owner)s cannot have a point of this kind: %(kinds)s.'),
                params={'owner': owner.code, 'kinds': ', '.join(str(kind.label) for kind in kinds_for(owner))})
        if self.kind == PointKind.MIDDLE and self.is_active and owner is not None:
            others = type(self).objects.filter(**{self.owner_type: owner}, kind=PointKind.MIDDLE, is_active=True)
            if others.exclude(pk=self.pk).exists():
                errors['kind'] = _('This owner already has an active middle point: it stands for its water.')
        if self.kind == PointKind.DEPTH:
            if self.depth_m is None:
                errors['depth_m'] = _('A depth point has a depth.')
            elif isinstance(owner, Tank):
                deepest = max((value for value in (owner.depth, owner.max_depth, owner.max_submersion_depth)
                               if value is not None), default=None)
                if deepest is not None and self.depth_m > deepest:
                    errors['depth_m'] = ValidationError(
                        _('%(unit)s is %(depth)s m deep: the point cannot be deeper.'),
                        params={'unit': owner.code, 'depth': format(deepest.normalize(), 'f')})
        if self.flow_share_pct is not None and self.is_active and owner is not None:
            total = self.other_shares() + self.flow_share_pct
            if total > 100:
                errors['flow_share_pct'] = ValidationError(
                    _('The outlets of %(owner)s would take %(total)s %% of its outflow: at most 100.'),
                    params={'owner': owner.code, 'total': format(total.normalize(), 'f')})
        if errors:
            raise ValidationError(errors)

    def delete_blockers(self):
        """A point with samples is not deleted: they stay in the history (make it inactive instead). Only a
        point deleted by itself is asked, never one that goes with its owner: those stay, out of sight."""
        if self._state.adding:
            return []
        from .water import WaterMeasurement
        count = WaterMeasurement.all_objects.filter(point=self).count()
        if not count:
            return []
        return [ngettext('It has %(count)d water sample in the history: make it inactive instead.',
                         'It has %(count)d water samples in the history: make it inactive instead.', count)
                % {'count': count}]
