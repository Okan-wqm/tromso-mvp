"""Dosing: the reagents that move a water on the Water Quality Management Chart, the recipes of two of them
that take it from its point to a target, and the simulator that adds amounts and follows the water step by
step (Operations › Water chemistry › Calculator). Ported from the source's engine
(libs/aquaculture-engines/src/water-chemistry/reagents.ts: REAGENTS, calcTwoReagentDosing,
calculateDosingRecipes, reagentDirectionLine, calcDosingVisualization, calcForwardDosing); where it was wrong
the bug document says so (WQ-40 on). Pure functions of floats, no database; the chemistry is
farm/water/chemistry.py.

What a reagent does. Dissolved, each moves the water along a fixed direction of the chart, per mmol of
reagent in a litre (Deffeyes 1965, Limnol. Oceanogr. 10: 412, his figure of the reagent vectors; Stumm &
Morgan 1996, Aquatic Chemistry, 3rd ed., 4.5; Loyless & Malone 1997, Prog. Fish-Cult. 59: 198, sodium
bicarbonate on the same chart):
- NaHCO₃: DIC +1, alkalinity +1 (it brings one HCO₃⁻);
- Na₂CO₃ and CaCO₃: DIC +1, alkalinity +2 (one CO₃²⁻); CaCO₃ dissolves only in water undersaturated with
  calcite, so it is slow or does nothing in most farm water;
- NaOH: alkalinity +1; Ca(OH)₂ and CaO (slaked to Ca(OH)₂ in the water): alkalinity +2; the DIC unchanged;
- CO₂ added: DIC +1; CO₂ stripped (aeration, a degasser): DIC −1; the alkalinity unchanged, CO₂ carries no
  charge;
- HCl: alkalinity −1, the DIC unchanged.
An amount is of the pure substance: g = mmol/L × M (g/mol) × V (m³). A trade product is weaker: hydrochloric
("muriatic") acid is sold at 31 to 37 % HCl, caustic soda lye at about 50 % NaOH, so their weight is the
amount divided by the strength. The calcium reagents add calcium too (1 mmol/L per mmol/L), which moves the
calcite and aragonite lines; the chart keeps the calcium entered.

After a dose the water is the chart's point at the new DIC and alkalinity, its pH the pH whose line passes
through it (chemistry.Equilibria.ph_at): mixed through, closed to the air while it mixes, as the source
computes it. Stripping cannot take the CO₂ below what the water holds in equilibrium with the air
(chemistry.co2_from_air): a step that would is flagged.

A recipe takes the water from its point to the target with two reagents: the move Δ = a v₁ + b v₂ with
a, b ≥ 0 (Cramer's rule on the two reagents' directions); no recipe when the two cannot reach the target
that way. The reagent whose direction has the smaller angle on the chart goes first (the source's order),
and the point between the two doses is the waypoint. As the source does: every pair of the chosen reagents,
a reagent left out under 0.001 g ("X only"), the same reagents once, a pair where one reagent adds
alkalinity and the other takes it away (an overshoot and a correction) only when nothing else reaches the
target, ranked by the reagents' places in REAGENTS (sodium bicarbonate first), at most MAX_RECIPES."""
import math
from dataclasses import dataclass, field

from django.utils.translation import gettext_lazy as _

from . import chemistry

# Standard atomic weights (IUPAC), as farm/water/chemistry.py's molar masses use them.
ATOMIC_WEIGHT = {'H': 1.00794, 'C': 12.0107, 'O': 15.9994, 'Na': 22.98976928, 'Ca': 40.078, 'Cl': 35.453}
MAX_RECIPES = 6
LEFT_OUT_G = 0.001         # a dose under this is left out of a recipe (the source's)
AT_TARGET = 0.001          # mmol/L and meq/L: closer than this the water is at its target (the source's)


def molar_mass(**atoms):
    """g/mol of a formula given as atom counts: molar_mass(Na=1, H=1, C=1, O=3)."""
    return sum(ATOMIC_WEIGHT[atom] * count for atom, count in atoms.items())


@dataclass(frozen=True)
class Reagent:
    """A reagent and its direction on the chart: the DIC (mmol) and the alkalinity (meq) one mmol of it adds."""
    key: str
    name: str
    formula: str
    molar_mass: float       # g/mol
    dic: float
    alkalinity: float

    @property
    def angle(self):
        """Its direction on the chart, DIC across and alkalinity up, from 0 to 2π (the source's `radians`)."""
        return math.atan2(self.alkalinity, self.dic) % (2 * math.pi)

    def unit_move(self):
        """Its direction scaled to one unit along DIC, or along alkalinity when it leaves the DIC alone (the
        source's reagentDirectionLine)."""
        scale = abs(self.dic) or abs(self.alkalinity)
        return self.dic / scale, self.alkalinity / scale


# The source's REAGENTS, in its order, which is also the order of practicality the recipes are ranked by.
REAGENTS = [
    Reagent('nahco3', _('Sodium bicarbonate'), 'NaHCO₃', molar_mass(Na=1, H=1, C=1, O=3), 1, 1),
    Reagent('na2co3', _('Sodium carbonate'), 'Na₂CO₃', molar_mass(Na=2, C=1, O=3), 1, 2),
    Reagent('naoh', _('Sodium hydroxide'), 'NaOH', molar_mass(Na=1, O=1, H=1), 0, 1),
    Reagent('caco3', _('Calcium carbonate'), 'CaCO₃', molar_mass(Ca=1, C=1, O=3), 1, 2),
    Reagent('caoh2', _('Calcium hydroxide'), 'Ca(OH)₂', molar_mass(Ca=1, O=2, H=2), 0, 2),
    Reagent('cao', _('Calcium oxide'), 'CaO', molar_mass(Ca=1, O=1), 0, 2),
    Reagent('co2', _('Carbon dioxide, added'), 'CO₂', molar_mass(C=1, O=2), 1, 0),
    Reagent('degas', _('Carbon dioxide, stripped'), '−CO₂', molar_mass(C=1, O=2), -1, 0),
    Reagent('hcl', _('Hydrochloric acid'), 'HCl', molar_mass(H=1, Cl=1), 0, -1),
]
BY_KEY = {reagent.key: reagent for reagent in REAGENTS}
# The source's starting choice (WaterChemistryPage.tsx).
DEFAULT_REAGENTS = ['nahco3', 'naoh', 'co2', 'degas']


# ---- recipes --------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Dose:
    """One reagent of a recipe: how much per litre and in the volume, and how it moves the water."""
    reagent: Reagent
    concentration: float            # mmol of reagent per litre
    grams: float | None             # in the volume; None without a volume
    delta_dic: float                # mmol/L
    delta_alkalinity: float         # meq/L

    @property
    def mg_l(self):
        """The dose as mg of reagent per litre, which is g per m³."""
        return self.concentration * self.reagent.molar_mass

    @property
    def kilograms(self):
        return None if self.grams is None else self.grams / 1000


@dataclass(frozen=True)
class Recipe:
    doses: list
    waypoint: tuple                 # (DIC, alkalinity) after the first reagent
    below_air: bool = False         # a stripping step would take the CO₂ below the air's

    @property
    def counter_productive(self):
        """One reagent adds alkalinity and the other takes it away: an overshoot and a correction."""
        return (any(dose.delta_alkalinity > 1e-9 for dose in self.doses)
                and any(dose.delta_alkalinity < -1e-9 for dose in self.doses))

    @property
    def priority(self):
        return sum(REAGENTS.index(dose.reagent) for dose in self.doses)


def split(start, end, first, second):
    """How much of each of two reagents takes the water from `start` to `end`, both (DIC mmol/L, alkalinity
    meq/L): (lower, a, higher, b), a and b in mmol/L, `lower` the reagent of the smaller angle; None when the
    move is not a sum of their directions with amounts ≥ 0 (they cannot reach it), or there is no move."""
    lower, higher = sorted((first, second), key=lambda reagent: reagent.angle)
    across, up = end[0] - start[0], end[1] - start[1]
    if abs(across) < 1e-6 and abs(up) < 1e-6:
        return None
    determinant = lower.dic * higher.alkalinity - lower.alkalinity * higher.dic
    if abs(determinant) < 1e-12:            # the same or opposite directions: no single way
        return None
    a = (across * higher.alkalinity - up * higher.dic) / determinant
    b = (lower.dic * up - lower.alkalinity * across) / determinant
    if a < -1e-9 or b < -1e-9:
        return None
    return lower, max(a, 0.0), higher, max(b, 0.0)


def _dose(reagent, concentration, volume):
    return Dose(reagent, concentration, None if volume is None else concentration * reagent.molar_mass * volume,
                concentration * reagent.dic, concentration * reagent.alkalinity)


def recipe(start, end, first, second, volume=None, below_air=None):
    """The recipe of two reagents from `start` to `end` (volume in m³; None gives the doses per litre only);
    None when they cannot reach it. `below_air(dic, alkalinity)` says whether a water's CO₂ is below the
    air's, to flag a stripping step that would go there."""
    found = split(start, end, first, second)
    if found is None:
        return None
    lower, a, higher, b = found
    waypoint = (start[0] + a * lower.dic, start[1] + a * lower.alkalinity)
    weight = 1.0 if volume is None else volume          # a dose is left out by its weight in the volume
    doses = [_dose(reagent, amount, volume) for reagent, amount in ((lower, a), (higher, b))
             if amount * reagent.molar_mass * weight > LEFT_OUT_G]
    if not doses:
        return None
    kept = {dose.reagent.key for dose in doses}
    stripped_to = [point for reagent, point in ((lower, waypoint), (higher, end))
                   if reagent.key == 'degas' and reagent.key in kept]
    flagged = below_air is not None and any(below_air(*point) for point in stripped_to)
    return Recipe(doses, waypoint, flagged)


def at_target(start, end):
    """The water is at its target: closer than AT_TARGET in DIC and in alkalinity."""
    return abs(end[0] - start[0]) < AT_TARGET and abs(end[1] - start[1]) < AT_TARGET


def recipes(start, end, chosen, volume=None, below_air=None):
    """The recipes from the water to the target with the chosen reagents (keys), practical ones first, at most
    MAX_RECIPES; none when the water is at the target."""
    if at_target(start, end):
        return []
    reagents = [reagent for reagent in REAGENTS if reagent.key in chosen]
    found, seen = [], set()
    for index, first in enumerate(reagents):
        for second in reagents[index + 1:]:
            made = recipe(start, end, first, second, volume, below_air)
            if made is None:
                continue
            same = tuple(sorted(dose.reagent.key for dose in made.doses))
            if same in seen:
                continue
            seen.add(same)
            found.append(made)
    productive = [made for made in found if not made.counter_productive]
    return sorted(productive or found, key=lambda made: made.priority)[:MAX_RECIPES]


# ---- the dosing layer of the chart ------------------------------------------------------------------------
LINE_LENGTH = 8             # the source's direction lines: 8 mmol/L along DIC (or meq/L along alkalinity)


@dataclass
class Visual:
    """What the chart's dosing layer draws, as the source does: one reagent chosen, its line from the water;
    two, both lines, the wedge between them and, when they reach the target, the path through the waypoint.
    In the chart's units."""
    lines: list = field(default_factory=list)          # [(reagent, [(DIC, alkalinity), ...])]
    wedge: list = field(default_factory=list)          # polygon
    path: list = field(default_factory=list)           # water → waypoint → target
    waypoint: tuple | None = None
    note: str = ''


def direction_line(start, reagent, length=LINE_LENGTH):
    across, up = reagent.unit_move()
    return [start, (start[0] + length * across, start[1] + length * up)]


def visual(start, end, chosen):
    """The dosing layer for the chosen reagents (keys, in the order chosen); `end` None without a target."""
    reagents = [BY_KEY[key] for key in chosen if key in BY_KEY]
    shown = Visual()
    if len(reagents) == 1:
        shown.lines = [(reagents[0], direction_line(start, reagents[0]))]
    elif len(reagents) == 2:
        shown.lines = [(reagent, direction_line(start, reagent)) for reagent in reagents]
        shown.wedge = [start, shown.lines[0][1][1], shown.lines[1][1][1]]
        found = split(start, end, *reagents) if end is not None else None
        if found is not None:
            lower, a, _higher, _b = found
            shown.waypoint = (start[0] + a * lower.dic, start[1] + a * lower.alkalinity)
            shown.path = [start, shown.waypoint, end]
        elif end is not None:
            shown.note = _('Dosing path: these two reagents cannot reach the target.')
    else:
        shown.note = _('Dosing path: tick one reagent to draw its line, or two to draw their path to the target.')
    return shown


# ---- the simulator --------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Step:
    """The water after a dose (the first step: before any). `ph` None: no water has this DIC and alkalinity
    (more CO₂ stripped than it holds, or no pH from 0 to 14 gives them); the simulation stops there."""
    reagent: Reagent | None
    grams: float
    dic: float
    alkalinity: float
    ph: float | None
    co2_mg_l: float | None
    below_air: bool = False


def simulate(eq, start, ph, amounts, volume, air_co2_mg_l=None):
    """The water after each amount (grams by reagent key) added in turn to `volume` m³, in REAGENTS' order
    (the source's), from `start` (DIC, alkalinity) at `ph`; a stripping step that takes the CO₂ below
    `air_co2_mg_l` is flagged. [] without an amount."""
    doses = [(reagent, amounts[reagent.key]) for reagent in REAGENTS if amounts.get(reagent.key)]
    if not doses:
        return []
    dic, alkalinity = start
    steps = [Step(None, 0.0, dic, alkalinity, ph, eq.co2(dic, ph) * chemistry.MG_CO2_PER_MMOL)]
    for reagent, grams in doses:
        concentration = grams / reagent.molar_mass / volume          # mmol/L
        dic += concentration * reagent.dic
        alkalinity += concentration * reagent.alkalinity
        reached = eq.ph_at(dic, alkalinity)
        if reached is None:
            steps.append(Step(reagent, grams, dic, alkalinity, None, None))
            break
        co2 = eq.co2(dic, reached) * chemistry.MG_CO2_PER_MMOL
        below = reagent.key == 'degas' and air_co2_mg_l is not None and co2 < air_co2_mg_l
        steps.append(Step(reagent, grams, dic, alkalinity, reached, co2, below))
    return steps
