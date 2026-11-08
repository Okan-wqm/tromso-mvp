from decimal import Decimal

from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.db import models
from django.db.models import Case, F, Q, Sum, Value, When
from django.db.models.functions import Coalesce, Round
from django.utils import timezone
from django.utils.translation import gettext, gettext_lazy as _

from core.models import AuditedModel, CodedMixin

from .production_department import ProductionDepartment
from .system import System


# ---- the choices ---------------------------------------------------------------------------------
class Kind(models.TextChoices):
    TANK = 'tank', _('Tank')
    POND = 'pond', _('Pond')
    CAGE = 'cage', _('Cage')


class Status(models.TextChoices):
    PREPARING = 'preparing', _('Preparing')
    ACTIVE = 'active', _('Active')
    HARVESTING = 'harvesting', _('Harvesting')
    CLEANING = 'cleaning', _('Cleaning')
    MAINTENANCE = 'maintenance', _('Maintenance')
    FALLOW = 'fallow', _('Fallow')
    QUARANTINE = 'quarantine', _('Quarantine')
    INACTIVE = 'inactive', _('Inactive')


class WaterType(models.TextChoices):
    FRESHWATER = 'freshwater', _('Freshwater')
    SALTWATER = 'saltwater', _('Saltwater')
    BRACKISH = 'brackish', _('Brackish')


class Shape(models.TextChoices):
    CIRCULAR = 'circular', _('Circular')
    RECTANGULAR = 'rectangular', _('Rectangular')
    SQUARE = 'square', _('Square')
    OVAL = 'oval', _('Oval')
    RACEWAY = 'raceway', _('Raceway')
    D_END = 'd_end', _('D-ended')
    OTHER = 'other', _('Other')


class Material(models.TextChoices):
    FIBERGLASS = 'fiberglass', _('Fibreglass (GRP)')
    CONCRETE = 'concrete', _('Concrete')
    HDPE = 'hdpe', _('HDPE')
    STEEL = 'steel', _('Steel')
    STAINLESS_STEEL = 'stainless_steel', _('Stainless steel')
    PVC = 'pvc', _('PVC')
    LINER = 'liner', _('Liner on a frame')
    OTHER = 'other', _('Other')


class PondType(models.TextChoices):
    EARTHEN = 'earthen', _('Earthen')
    LINED = 'lined', _('Lined')


class Liner(models.TextChoices):
    NONE = 'none', _('None (bare soil)')
    CLAY = 'clay', _('Compacted clay')
    HDPE = 'hdpe', _('HDPE')
    PVC = 'pvc', _('PVC')
    EPDM = 'epdm', _('EPDM')
    CONCRETE = 'concrete', _('Concrete')


class WaterSource(models.TextChoices):
    WELL = 'well', _('Well (groundwater)')
    SPRING = 'spring', _('Spring')
    RIVER = 'river', _('River or stream')
    RESERVOIR = 'reservoir', _('Lake or reservoir')
    SEA = 'sea', _('Sea or estuary')
    RAIN = 'rain', _('Rain and run-off')
    MIXED = 'mixed', _('Mixed')


class CageType(models.TextChoices):
    FLOATING = 'floating', _('Floating')
    SUBMERSIBLE = 'submersible', _('Submersible')


class Frame(models.TextChoices):
    HDPE = 'hdpe', _('HDPE')
    STEEL = 'steel', _('Steel')
    GALVANISED = 'galvanized', _('Galvanised steel')


class NetMaterial(models.TextChoices):
    NYLON = 'nylon', _('Nylon')
    POLYETHYLENE = 'polyethylene', _('Polyethylene')
    POLYESTER = 'polyester', _('Polyester (PET)')
    COPPER_ALLOY = 'copper_alloy', _('Copper alloy')


# ---- what each kind of unit is described by -----------------------------------------------------
# The measures a shape is entered by. A square is entered by its side; its width is that side (stored,
# so every rectangle reads length × width alike). A shape of its own ("other") is entered by its volume.
SHAPE_MEASURES = {
    Shape.CIRCULAR: ('diameter',),
    Shape.RECTANGULAR: ('length', 'width'),
    Shape.SQUARE: ('length',),
    Shape.OVAL: ('length', 'width'),
    Shape.RACEWAY: ('length', 'width'),
    Shape.D_END: ('length', 'width'),
    Shape.OTHER: ('stated_volume_m3',),
}
STORED_WIDTH = (Shape.RECTANGULAR, Shape.SQUARE, Shape.OVAL, Shape.RACEWAY, Shape.D_END)
LONG_SIDE_FIRST = (Shape.OVAL, Shape.D_END)   # the length is the long axis: never shorter than the width

# The choices a kind of unit offers for each choice field; a field not listed for a kind stays empty.
OFFERED = {
    'shape': {Kind.TANK: Shape.values, Kind.CAGE: [Shape.CIRCULAR, Shape.SQUARE]},
    'material': {Kind.TANK: Material.values},
    'pond_type': {Kind.POND: PondType.values},
    'liner_type': {Kind.POND: Liner.values},
    'water_source': {Kind.POND: WaterSource.values},
    'cage_type': {Kind.CAGE: CageType.values},
    'frame_type': {Kind.CAGE: Frame.values},
    'net_material': {Kind.CAGE: NetMaterial.values},
}
# An earthen pond is bare soil or compacted clay; a membrane or concrete makes it a lined pond.
LINERS = {
    PondType.EARTHEN: [Liner.NONE, Liner.CLAY],
    PondType.LINED: [Liner.HDPE, Liner.PVC, Liner.EPDM, Liner.CONCRETE],
}
# What a kind of unit cannot be saved without, besides its shape's measures and the depth.
REQUIRED = {
    Kind.TANK: ('shape', 'material'),
    Kind.POND: ('pond_type', 'surface_area_m2'),
    Kind.CAGE: ('cage_type', 'shape'),
}

# The bounds of every measure per kind, (lowest, highest) in the field's unit. One table feeds the
# form's checks and help texts and the database's CHECK constraints; a measure not listed for a kind
# is not one it has. Why each bound: docs/aquaculture-platform-bugs.md, "Tanks, ponds and cages".
LIMITS = {
    'diameter': {Kind.TANK: ('0.1', '50'), Kind.CAGE: ('1', '150')},
    'length': {Kind.TANK: ('0.1', '200'), Kind.CAGE: ('1', '100')},
    'width': {Kind.TANK: ('0.1', '50'), Kind.CAGE: ('1', '100')},
    'stated_volume_m3': {Kind.TANK: ('0.001', '200000')},
    'depth': {Kind.TANK: ('0.1', '20'), Kind.POND: ('0.1', '10'), Kind.CAGE: ('1', '100')},
    'surface_area_m2': {Kind.POND: ('1', '10000000')},
    'max_depth': {Kind.POND: ('0.1', '20')},
    'mesh_size_mm': {Kind.CAGE: ('1', '200')},
    'max_submersion_depth': {Kind.CAGE: ('1', '100')},
    'max_density_kg_m3': {Kind.TANK: ('0.01', '500'), Kind.POND: ('0.01', '50'), Kind.CAGE: ('0.01', '300')},
}
# A liner's thickness by liner: a geomembrane (HDPE, PVC, EPDM) is millimetres thick, concrete centimetres.
LINER_THICKNESS = {
    Liner.HDPE: ('0.2', '5'), Liner.PVC: ('0.2', '5'), Liner.EPDM: ('0.2', '5'), Liner.CONCRETE: ('25', '500'),
}

# The fields that depend on the kind and are emptied when the kind, shape, pond type or cage type no
# longer uses them. The depth is every kind's (a tank's depth, a pond's average depth, a cage's net depth).
KIND_FIELDS = (
    'shape', 'material', 'diameter', 'length', 'width', 'stated_volume_m3', 'water_depth',
    'pond_type', 'water_source', 'surface_area_m2', 'max_depth', 'liner_type', 'liner_thickness_mm',
    'cage_type', 'max_submersion_depth', 'frame_type', 'net_material', 'mesh_size_mm',
)
# The fields the volume is calculated from: they cannot change while fish are in the unit.
VOLUME_FIELDS = ('shape', 'diameter', 'length', 'width', 'stated_volume_m3', 'depth', 'water_depth',
                 'surface_area_m2')

# The status machine, as the source has it (tank-status.policy.ts): from each status, the ones a unit
# can move to. Harvesting, cleaning and quarantine follow from an earlier status, so a new unit starts
# in one of the others.
TRANSITIONS = {
    Status.INACTIVE: (Status.PREPARING,),
    Status.PREPARING: (Status.ACTIVE, Status.INACTIVE),
    Status.ACTIVE: (Status.HARVESTING, Status.MAINTENANCE, Status.QUARANTINE, Status.FALLOW),
    Status.HARVESTING: (Status.CLEANING,),
    Status.CLEANING: (Status.PREPARING, Status.MAINTENANCE, Status.FALLOW),
    Status.MAINTENANCE: (Status.PREPARING, Status.INACTIVE),
    Status.FALLOW: (Status.PREPARING,),
    Status.QUARANTINE: (Status.ACTIVE, Status.CLEANING),
}
# A status says whether fish are in the unit: active and harvesting need fish, preparing, fallow,
# cleaning and inactive need none; maintenance and quarantine can be either. Stocking and emptying a
# unit move it in and out of these by themselves (farm/stock/services.py); the form refuses a status
# that contradicts the fish in it.
NEEDS_FISH = (Status.ACTIVE, Status.HARVESTING)
NEEDS_NO_FISH = (Status.PREPARING, Status.FALLOW, Status.CLEANING, Status.INACTIVE)
# A new unit holds no fish, so it does not start as active.
STARTING_STATUSES = (Status.PREPARING, Status.FALLOW, Status.MAINTENANCE, Status.INACTIVE)


def described_by(kind, shape='', pond_type='', cage_type=''):
    """The kind-dependent fields a unit is described by, in the order the form shows them: a tank by its
    shape, material, the shape's measures and its water depth; a pond by its type, area, depths and
    liner; a cage by its type, shape, the shape's measures, its submersion depth when it is submersible,
    and its net and frame. The depth comes with every kind."""
    if kind == Kind.TANK:
        return ['shape', 'material', *SHAPE_MEASURES.get(shape, ()), 'depth', 'water_depth']
    if kind == Kind.POND:
        return ['pond_type', 'water_source', 'surface_area_m2', 'depth', 'max_depth', 'water_depth', 'liner_type',
                *(['liner_thickness_mm'] if pond_type == PondType.LINED else [])]
    if kind == Kind.CAGE:
        return ['cage_type', 'shape', *SHAPE_MEASURES.get(shape, ()), 'depth',
                *(['max_submersion_depth'] if cage_type == CageType.SUBMERSIBLE else []),
                'net_material', 'mesh_size_mm', 'frame_type']
    return []


# ---- the derived values, as the database computes them -------------------------------------------
PI = Value(Decimal('3.14159265358979'))


def water_surface():
    """The unit's water surface in m², by kind and shape: a pond's area as entered; a circle π·d²/4; an
    ellipse π·L·W/4 (L and W its axes); a D-ended tank, a rectangle with a half circle at each end, the
    rectangle (L − W)·W plus the two half circles π·W²/4 (L its overall length); a rectangle, a square
    or a raceway L·W. A shape of its own has its volume entered, so its surface is that volume over the
    depth (its walls taken as upright, like every other shape's)."""
    return Case(
        When(kind=Kind.POND, then=F('surface_area_m2')),
        When(shape=Shape.CIRCULAR, then=PI * F('diameter') * F('diameter') / 4),
        When(shape=Shape.OVAL, then=PI * F('length') * F('width') / 4),
        When(shape=Shape.D_END, then=(F('length') - F('width')) * F('width') + PI * F('width') * F('width') / 4),
        When(shape__in=[Shape.RECTANGULAR, Shape.SQUARE, Shape.RACEWAY], then=F('length') * F('width')),
        When(shape=Shape.OTHER, then=F('stated_volume_m3') / F('depth')),
    )


def _volume(depth):
    """The water surface times a depth, in m³ to the litre."""
    return Round(water_surface() * depth, 3)


def _range(name, low, high, **condition):
    return Q(**condition, **{f'{name}__gte': Decimal(low), f'{name}__lte': Decimal(high)})


def _check(name, condition, message=None):
    """A CHECK constraint on the table; `message` when a person can meet it outside the form (the admin's
    restore), else Django's own wording."""
    return models.CheckConstraint(condition=condition, name=f'chk_tanks_{name}',
                                  **({'violation_error_message': message} if message else {}))


def _either(conditions):
    return Q(*conditions, _connector=Q.OR)


def _constraints():
    """The rules the database itself holds. Each is checked by the form first, with its message on
    the field; these keep the rows right whatever writes them."""
    def used_by(shapes, name):
        """`name` is filled for these shapes and empty for every other."""
        return (Q(shape__in=shapes) & Q(**{f'{name}__isnull': False})) | (
            ~Q(shape__in=shapes) & Q(**{f'{name}__isnull': True}))

    def given(name):
        """A measure (a number, in LIMITS) is missing when NULL, a choice when empty."""
        return Q(**{f'{name}__isnull': False}) if name in LIMITS else ~Q(**{name: ''})

    measured_by = {name: [shape for shape, names in SHAPE_MEASURES.items() if name in names]
                   for name in ('diameter', 'length', 'stated_volume_m3')}
    return [
        _check('kind', Q(kind__in=Kind.values)),
        _check('status', Q(status__in=Status.values)),
        _check('water_type', Q(water_type__in=WaterType.values)),
        *(_check(f'{name}_by_kind', Q(**{name: ''}) | _either(
            Q(kind=kind, **{f'{name}__in': values}) for kind, values in offered.items()))
          for name, offered in OFFERED.items()),
        *(_check(f'{kind}_required', ~Q(kind=kind) | Q(*map(given, names))) for kind, names in REQUIRED.items()),
        *(_check(f'{name}_by_shape', used_by(shapes, name)) for name, shapes in measured_by.items()),
        _check('width_by_shape', used_by(STORED_WIDTH, 'width')),
        _check('square_sides', ~Q(shape=Shape.SQUARE) | Q(width=F('length'))),
        _check('long_side_first', ~Q(shape__in=LONG_SIDE_FIRST) | Q(length__gte=F('width'))),
        _check('water_depth', Q(water_depth__isnull=True)
               | Q(kind__in=[Kind.TANK, Kind.POND], water_depth__gt=0, water_depth__lte=F('depth'))),
        _check('max_depth', Q(max_depth__isnull=True) | Q(max_depth__gte=F('depth'))),
        _check('liner_by_pond_type', Q(pond_type='', liner_type='')
               | Q(pond_type=PondType.EARTHEN, liner_type__in=['', *LINERS[PondType.EARTHEN]])
               | Q(pond_type=PondType.LINED, liner_type__in=LINERS[PondType.LINED]),
               _('An earthen pond is bare soil or compacted clay; a lined pond has a membrane or concrete, and '
                 'needs it.')),
        _check('liner_thickness', Q(liner_thickness_mm__isnull=True) | _either(
            _range('liner_thickness_mm', low, high, pond_type=PondType.LINED, liner_type=liner)
            for liner, (low, high) in LINER_THICKNESS.items())),
        _check('submersion', Q(max_submersion_depth__isnull=True) | Q(cage_type=CageType.SUBMERSIBLE)),
        *(_check(f'{name}_range', Q(**{f'{name}__isnull': True}) | _either(
            _range(name, low, high, kind=kind) for kind, (low, high) in by_kind.items()))
          for name, by_kind in LIMITS.items()),
    ]


class Tank(CodedMixin, AuditedModel):
    """A unit fish are held in: a tank, a pond or a cage. Source table: farm.tanks.

    The class and the table keep the source's name (its later tables point at `tankId`), but a person
    reads "unit": a tank, a pond and a cage are one table of three kinds, and the menu calls the tab
    Tanks, ponds & cages. The kind is chosen once; each kind has its own typed columns (a pond's area
    and liner, a cage's net), and the columns another kind uses stay empty, which the database checks.

    Derived values are derived, never typed: the volume, the water volume and the max biomass are
    generated columns the database computes from the measures (`water_surface()`), so a stored volume
    always matches its unit's measures, whatever wrote the row; the freeboard is the depth less the
    water depth. Only a shape of its own ("other") has its volume entered.

    Master data only: the fish in a unit (count, biomass, batches) are the stock ledger's
    (farm/models/stock.py), and `has_stock()` is the one place that asks it; stocking and emptying the
    unit move its status (farm/stock/services.py). Differences from the source: its own tab instead of
    the equipment form; the code is typed and kept; every pond and cage field has a column; the system
    must be on the production department's site and in that production department when it belongs to
    one; the status machine is in one place and refuses statuses a new unit cannot start in, and
    statuses that contradict the fish in it; the
    unique code and regulatory unit ID are among live units. Not ported: the sensor link, the
    equipment type, isActive, the stock mirrors, the maintenance dates, and the location, water flow
    and aeration JSON (no screen wrote them)."""

    Kind, Status, WaterType, Shape, Material = Kind, Status, WaterType, Shape, Material
    PondType, Liner, WaterSource, CageType, Frame, NetMaterial = (
        PondType, Liner, WaterSource, CageType, Frame, NetMaterial)

    # A deleted production department takes its units with it (as the source does); a deleted system
    # leaves its units in place, out of any system (core.softdelete).
    production_department = models.ForeignKey(
        ProductionDepartment, on_delete=models.CASCADE, related_name='tanks', verbose_name=_('Production department'),
    )
    system = models.ForeignKey(
        System, null=True, blank=True, on_delete=models.SET_NULL, related_name='tanks', verbose_name=_('System'),
    )
    name = models.CharField(_('Name'), max_length=100)
    code = models.CharField(_('Code'), max_length=20)
    kind = models.CharField(_('Kind'), max_length=10, choices=Kind.choices)
    status = models.CharField(_('Status'), max_length=20, choices=Status.choices, default=Status.PREPARING)
    status_changed_at = models.DateTimeField(_('Status since'), null=True, blank=True, editable=False)
    status_reason = models.CharField(_('Reason for the status'), max_length=500, blank=True)
    water_type = models.CharField(_('Water type'), max_length=20, choices=WaterType.choices)
    regulatory_unit_id = models.CharField(_('Regulatory unit ID'), max_length=50, blank=True)

    # Tanks and cages
    shape = models.CharField(_('Shape'), max_length=20, choices=Shape.choices, blank=True)
    material = models.CharField(_('Material'), max_length=20, choices=Material.choices, blank=True)
    diameter = models.DecimalField(_('Diameter (m)'), max_digits=7, decimal_places=2, null=True, blank=True)
    length = models.DecimalField(_('Length (m)'), max_digits=7, decimal_places=2, null=True, blank=True)
    width = models.DecimalField(_('Width (m)'), max_digits=7, decimal_places=2, null=True, blank=True)
    stated_volume_m3 = models.DecimalField(_('Stated volume (m³)'), max_digits=13, decimal_places=3, null=True,
                                           blank=True)
    # Every kind: a tank's depth, a pond's average depth, a cage's net depth.
    depth = models.DecimalField(_('Depth (m)'), max_digits=7, decimal_places=2)
    water_depth = models.DecimalField(_('Water depth (m)'), max_digits=7, decimal_places=2, null=True, blank=True)
    # Ponds
    pond_type = models.CharField(_('Pond type'), max_length=10, choices=PondType.choices, blank=True)
    water_source = models.CharField(_('Water source'), max_length=10, choices=WaterSource.choices, blank=True)
    surface_area_m2 = models.DecimalField(_('Surface area (m²)'), max_digits=12, decimal_places=2, null=True,
                                          blank=True)
    max_depth = models.DecimalField(_('Max depth (m)'), max_digits=7, decimal_places=2, null=True, blank=True)
    liner_type = models.CharField(_('Liner'), max_length=10, choices=Liner.choices, blank=True)
    liner_thickness_mm = models.DecimalField(_('Liner thickness (mm)'), max_digits=5, decimal_places=2, null=True,
                                             blank=True)
    # Cages
    cage_type = models.CharField(_('Cage type'), max_length=12, choices=CageType.choices, blank=True)
    max_submersion_depth = models.DecimalField(_('Max submersion depth (m)'), max_digits=7, decimal_places=2,
                                               null=True, blank=True)
    frame_type = models.CharField(_('Frame'), max_length=12, choices=Frame.choices, blank=True)
    net_material = models.CharField(_('Net material'), max_length=15, choices=NetMaterial.choices, blank=True)
    mesh_size_mm = models.DecimalField(_('Mesh size (mm)'), max_digits=4, decimal_places=1, null=True, blank=True)

    # Capacity: the density is entered, the rest is computed by the database.
    max_density_kg_m3 = models.DecimalField(_('Max density (kg/m³)'), max_digits=6, decimal_places=2)
    volume_m3 = models.GeneratedField(
        expression=_volume(F('depth')), output_field=models.DecimalField(max_digits=13, decimal_places=3),
        db_persist=True, verbose_name=_('Volume (m³)'),
    )
    water_volume_m3 = models.GeneratedField(
        expression=_volume(F('water_depth')), output_field=models.DecimalField(max_digits=13, decimal_places=3),
        db_persist=True, verbose_name=_('Water volume (m³)'),
    )
    # The most fish the unit may hold: its effective volume (the water volume, else the volume) at the max density.
    max_biomass_kg = models.GeneratedField(
        expression=Round(_volume(Coalesce(F('water_depth'), F('depth'))) * F('max_density_kg_m3'), 2),
        output_field=models.DecimalField(max_digits=14, decimal_places=2), db_persist=True,
        verbose_name=_('Max biomass (kg)'),
    )

    installation_date = models.DateField(_('Installation date'), null=True, blank=True)
    description = models.CharField(_('Description'), max_length=1000, blank=True)
    notes = models.CharField(_('Notes'), max_length=2000, blank=True)

    class Meta:
        db_table = 'tanks'
        ordering = ['name']
        verbose_name = _('unit')
        verbose_name_plural = _('units')
        constraints = [
            models.UniqueConstraint(
                fields=['code'], condition=Q(is_deleted=False), name='uq_tanks_code_live',
                violation_error_message=_('Another unit already uses this code.'),
            ),
            # A unit's number is the locality's (merd 1 on two sites is two units, OUR-07). The database holds it per
            # production department, all a constraint can see; clean() and check_stock hold it per site.
            models.UniqueConstraint(
                fields=['production_department', 'regulatory_unit_id'],
                condition=Q(is_deleted=False) & ~Q(regulatory_unit_id=''),
                name='uq_tanks_regulatory_unit_id_live',
                violation_error_message=_('Another unit of the site already has this regulatory unit ID.'),
            ),
            *_constraints(),
        ]
        indexes = [models.Index(fields=['kind']), models.Index(fields=['status'])]

    # ---- what the unit is described by ----------------------------------------------------------
    def described_by(self):
        return described_by(self.kind, self.shape, self.pond_type, self.cage_type)

    def tidy(self):
        """Empties the fields its kind and shape (or pond or cage type) do not use, and derives what is
        derived: a square's width is its side."""
        kept = set(self.described_by())
        for name in KIND_FIELDS:
            if name not in kept:
                setattr(self, name, '' if isinstance(self._meta.get_field(name), models.CharField) else None)
        if self.shape == Shape.SQUARE:
            self.width = self.length

    def subtype(self):
        """What sort of tank, pond or cage it is, as the list shows it: a tank's shape, a pond's type, a
        cage's type and shape."""
        parts = {Kind.TANK: [self.get_shape_display()], Kind.POND: [self.get_pond_type_display()],
                 Kind.CAGE: [self.get_cage_type_display(), self.get_shape_display()]}
        return ' · '.join(str(part) for part in parts.get(self.kind, []) if part)

    @property
    def freeboard(self):
        """How far the water stands below the rim, in m: the depth less the water depth."""
        if self.water_depth is None or self.depth is None:
            return None
        return self.depth - self.water_depth

    # ---- stock ------------------------------------------------------------------------------------
    def has_stock(self):
        """Whether fish are in the unit now: the sum of its live stock lines (Operations › Production
        units). The stock service keeps every batch's share of a unit at 0 or more on every day, so a
        positive sum means at least one batch is in it. Every rule that depends on fish asks this one
        method: the statuses that need fish or none, a unit with fish cannot be deleted, and its size
        cannot change while they are in it."""
        if self._state.adding:
            return False
        from .stock import StockMovement
        total = StockMovement.objects.filter(unit=self, operation__is_deleted=False).aggregate(
            fish=Sum('count_delta'))['fish']
        return (total or 0) > 0

    def has_history(self):
        """Whether the stock ledger has live lines in the unit, now or in the past: its figures belong to its site
        (the reports to the authorities are per locality)."""
        if self._state.adding:
            return False
        from .stock import StockMovement
        return StockMovement.objects.filter(unit=self, operation__is_deleted=False).exists()

    def same_number_on_site(self):
        """Another live unit of the same site with this unit's regulatory unit ID (none when it has none)."""
        if not self.regulatory_unit_id or not self.production_department_id:
            return None
        site_id = self.production_department.site_id
        others = type(self).objects.filter(regulatory_unit_id=self.regulatory_unit_id).exclude(pk=self.pk)
        others = others.filter(production_department__site_id=site_id) if site_id else others.filter(
            production_department_id=self.production_department_id)
        return others.first()

    def _check_site(self, errors):
        """A unit with stock lines stays on its site: moved to a production department of another site, its past
        stock, feedings and counts would be reported for the other locality."""
        if self._state.adding or not self.production_department_id or 'production_department' in errors:
            return
        site_now = (type(self).all_objects.filter(pk=self.pk)
                    .values_list('production_department__site_id', flat=True).first())
        if site_now != self.production_department.site_id and self.has_history():
            errors['production_department'] = ValidationError(
                _('It has stock records on its site: it can only move to a production department of the same site.'))

    def _check_number(self, errors):
        if 'regulatory_unit_id' not in errors and self.same_number_on_site() is not None:
            errors['regulatory_unit_id'] = ValidationError(
                _('Another unit of the site already has this regulatory unit ID.'))

    def withdrawal_blockers(self):
        """Why the unit is not deleted or restored now: its treatments, feedings and samples are what the withdrawals
        of the fish ever in it are worked out from, so a withdrawal that holds them waits
        (farm.health.withdrawal.held_reached; the withdrawal gate's rule, farm/apps.py)."""
        from ..health.withdrawal import held_reached
        return held_reached([self.pk])

    def delete_blockers(self):
        if self.has_stock():
            return [gettext('It holds fish: move or harvest them first.'), *self.withdrawal_blockers()]
        return self.withdrawal_blockers()

    # ---- status -----------------------------------------------------------------------------------
    def stored(self):
        """The status and the measures as the database holds them now; None for a new unit."""
        if self._state.adding:
            return None
        return type(self).all_objects.filter(pk=self.pk).values('status', 'status_reason', *VOLUME_FIELDS).first()

    def status_blocker(self, status):
        """Why the unit cannot be given `status` now, for its fish; None when it can."""
        if status in NEEDS_FISH and not self.has_stock():
            if status == Status.HARVESTING:
                return gettext('A unit can be harvested only while fish are in it.')
            return gettext('A unit becomes active when fish are stocked in it (Operations › Production units).')
        if status in NEEDS_NO_FISH and self.has_stock():
            if status == Status.INACTIVE:
                return gettext('A unit with fish in it cannot be made inactive: move or harvest them first.')
            return gettext('Fish are in the unit, so it cannot be %(status)s: move or harvest them first.') % {
                'status': str(Status(status).label).lower()}
        return None

    def next_statuses(self):
        """The statuses the form offers: for a new unit those it can start in, otherwise its current
        one and those it can move to now."""
        if self._state.adding:
            candidates = STARTING_STATUSES
        else:
            candidates = (self.status, *TRANSITIONS.get(self.status, ()))
        return [status for status in candidates
                if status == self.status and not self._state.adding or self.status_blocker(status) is None]

    def _check_status(self, stored, errors):
        if stored is None:
            if self.status not in STARTING_STATUSES:
                errors['status'] = ValidationError(
                    _('A new unit starts as one of: %(statuses)s.'),
                    params={'statuses': ', '.join(str(Status(status).label).lower() for status in STARTING_STATUSES)})
            return
        old = stored['status']
        if self.status == old:
            return
        if self.status not in TRANSITIONS.get(old, ()):
            errors['status'] = ValidationError(
                _('A unit cannot go from %(old)s to %(new)s.'),
                params={'old': str(Status(old).label).lower(), 'new': str(Status(self.status).label).lower()})
        elif blocker := self.status_blocker(self.status):
            errors['status'] = blocker

    # ---- links and measures -----------------------------------------------------------------------
    def _check_system(self, errors):
        if not self.system_id or not self.production_department_id:
            return
        system, department = self.system, self.production_department
        if system.is_deleted:
            errors['system'] = _('This system is deleted.')
        elif department.site_id is None:
            errors['system'] = _('The production department is not on any site, so its units cannot be in a system.')
        elif system.site_id != department.site_id:
            errors['system'] = _('The system is on another site than the production department.')
        elif system.production_department_id and system.production_department_id != department.pk:
            errors['system'] = ValidationError(
                _('The system belongs to another production department: %(department)s.'),
                params={'department': system.production_department})

    def _check_measures(self, errors):
        if self.water_depth is not None and self.water_depth <= 0:
            errors['water_depth'] = _('Leave the water depth empty, or give one above 0.')
        elif self.water_depth is not None and self.depth is not None and self.water_depth > self.depth:
            errors['water_depth'] = _('The water cannot stand higher than the depth.')
        if self.max_depth is not None and self.depth is not None and self.max_depth < self.depth:
            errors['max_depth'] = _('The deepest point cannot be shallower than the average depth.')
        if (self.shape in LONG_SIDE_FIRST and self.length is not None and self.width is not None
                and self.width > self.length):
            errors['width'] = _('The width cannot be more than the length.')
        if self.liner_thickness_mm is not None and self.liner_type in LINER_THICKNESS:
            low, high = LINER_THICKNESS[self.liner_type]
            if not Decimal(low) <= self.liner_thickness_mm <= Decimal(high):
                errors['liner_thickness_mm'] = ValidationError(
                    _('This liner is %(low)s to %(high)s mm thick.'), params={'low': low, 'high': high})

    def clean(self):
        super().clean()
        self.tidy()
        errors = {}
        stored = self.stored()
        self._check_status(stored, errors)
        self._check_system(errors)
        self._check_measures(errors)
        if stored and self.has_stock() and any(getattr(self, name) != stored[name] for name in VOLUME_FIELDS):
            errors[NON_FIELD_ERRORS] = _('Fish are in it, so its size cannot change: move or harvest them first.')
        self._check_site(errors)
        self._check_number(errors)
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        """Tidies the kind-dependent fields, and stamps a status change: when the status differs from the
        stored one it records the moment, and a reason left as it was belongs to the old status, so it
        is cleared."""
        self.tidy()
        stored = self.stored()
        if stored is None or self.status != stored['status']:
            self.status_changed_at = timezone.now()
            if stored is not None and self.status_reason == stored['status_reason']:
                self.status_reason = ''
        super().save(*args, **kwargs)
