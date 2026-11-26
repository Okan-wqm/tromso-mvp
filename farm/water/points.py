"""Sampling points: the points a new unit or system starts with, and what is said of a set of them that no single
row can hold (farm/models/water_point.py has the model and the rules one row can).

- `DEFAULTS` is the one template of the points an owner starts with, and `create_defaults` the one function that
  makes them, so the activity log records them like any change: a tank gets an inlet, a middle, a side outlet and a
  bottom drain; a pond an inlet, a middle and an outlet; a cage its middle; a system its loop. A piece of equipment
  gets none (its inlet and outlets are the person's to add). The Tank and System tabs call it when a record is
  created (their `after_save`); migration farm/0019 made them for the units and systems that existed before the points
  did. The names are stored as written here, in English, like any name a person types.
- `share_notes` reports the owners whose outlet shares do not add up to 100 %: the database cannot hold a rule that
  spans rows, so the form refuses more than 100 (SamplingPoint.clean) and the list says when it is less."""
from dataclasses import dataclass
from decimal import Decimal

from core import access, audit
from farm.models import SamplingPoint, Tank
from farm.models.water_point import EQUIPMENT, OUTLET_KINDS, SYSTEM, UNIT, PointKind, owner_type_of

# [(kind, name)] by what the owner is: a unit's kind, or SYSTEM.
# Who may create an owner's points: who may create the owner (asked here, whoever calls: the data-layering audit, L-6).
ADD = {UNIT: 'farm.add_tank', SYSTEM: 'farm.add_system', EQUIPMENT: 'farm.add_equipment'}
DEFAULTS = {
    Tank.Kind.TANK: [(PointKind.INLET, 'Inlet'), (PointKind.MIDDLE, 'Middle'), (PointKind.SIDE_OUTLET, 'Side outlet'),
                     (PointKind.BOTTOM_DRAIN, 'Bottom drain')],
    Tank.Kind.POND: [(PointKind.INLET, 'Inlet'), (PointKind.MIDDLE, 'Middle'), (PointKind.OUTLET, 'Outlet')],
    Tank.Kind.CAGE: [(PointKind.MIDDLE, 'Middle')],
    SYSTEM: [(PointKind.MIDDLE, 'Loop')],
}
# What the activity log compares for a point: where it is and everything it states.
LOGGED = ['unit', 'system', 'equipment', 'name', 'kind', 'depth_m', 'flow_m3_h', 'flow_share_pct', 'is_active',
          'description']


def template_for(owner_type, unit_kind=''):
    """[(kind, name)] a new owner of that type starts with (for a unit, of that kind of unit); none for a piece of
    equipment. Migration farm/0019 made the points of the units and systems that existed before the points did from
    its own copy of this template (a migration never reads app code that may change)."""
    if owner_type == EQUIPMENT:
        return []
    return DEFAULTS[unit_kind if owner_type == UNIT else SYSTEM]


def default_points(owner):
    """[(kind, name)] a new owner starts with."""
    return template_for(owner_type_of(owner), getattr(owner, 'kind', ''))


def snapshot(point):
    """The point as the activity log stores it: the fields, under their labels, in English."""
    with audit.source_language():
        return audit.snapshot(point, LOGGED)


def create_defaults(user, owner):
    """Creates the points a new owner starts with (`default_points`), each logged as created by `user`. A point
    whose name the owner already has is left as it is, so it can be run again. Returns the points it created.
    Call it inside the transaction that saves the owner. Who may create no owner at all is refused before the owner is
    read; then the right to create this one is asked."""
    access.require_any(user, *ADD.values())
    owner_type = owner_type_of(owner)
    access.require(user, ADD[owner_type])
    existing = list(SamplingPoint.all_objects.filter(**{owner_type: owner}, is_deleted=False))
    named = {point.name.lower() for point in existing}
    has_middle = any(point.kind == PointKind.MIDDLE and point.is_active for point in existing)
    created = []
    for kind, name in default_points(owner):
        if name.lower() in named or (kind == PointKind.MIDDLE and has_middle):
            continue
        point = SamplingPoint.all_objects.create(**{owner_type: owner}, kind=kind, name=name, created_by=user,
                                                 updated_by=user)
        audit.record_create(user, point, snapshot(point))
        created.append(point)
    return created


@dataclass(frozen=True)
class ShareNote:
    """An owner whose active outlets state shares that do not add up to 100 %."""
    owner: object
    total: Decimal
    outlets: int

    @property
    def over(self):
        return self.total > 100


def share_notes(site=None):
    """[ShareNote] of the live owners (of `site`, when given) with at least one active outlet that states a share and
    shares that add up to something other than 100 %, in owner code order. An owner whose outlets state none is not
    reported: nothing is claimed about it."""
    outlets = (SamplingPoint.objects.filter(is_active=True, kind__in=OUTLET_KINDS, flow_share_pct__isnull=False)
               .with_owners())
    totals = {}
    for point in outlets:
        owner = point.owner
        if site is not None and point.site != site:
            continue
        total, count = totals.get(owner.pk, (owner, Decimal(0), 0))[1:]
        totals[owner.pk] = (owner, total + point.flow_share_pct, count + 1)
    notes = [ShareNote(owner, total, count) for owner, total, count in totals.values() if total != 100]
    return sorted(notes, key=lambda note: note.owner.code)
