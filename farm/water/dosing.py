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
  calcite (soft, acid fresh water), and slowly: in sea water and in hard or alkaline farm water it does not;
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
(chemistry.co2_from_air): a simulator step that would is flagged, and a recipe whose stripping would end below
it in either order of its two doses (the order does not change where the water ends, only the CO₂ at which
the stripping stops: it can be done first or last).

A recipe takes the water from its point to the target with two reagents: the move Δ = a v₁ + b v₂ with
a, b ≥ 0 (Cramer's rule on the two reagents' directions); no recipe when the two cannot reach the target
that way. The reagent whose direction has the smaller angle on the chart goes first (the source's order),
and the point between the two doses is the waypoint. As the source does: every pair of the chosen reagents,
a reagent left out under 0.001 g ("X only"), the same reagents once, a pair where one reagent adds
alkalinity and the other takes it away (an overshoot and a correction) only when nothing else reaches the
target, ranked by the reagents' places in REAGENTS (sodium bicarbonate first), at most MAX_RECIPES."""
from dataclasses import dataclass, field

from django.utils.translation import gettext_lazy as _

from . import messages, native

MAX_RECIPES = 6              # the core's (chemcore/core/src/dosing.rs, where the rules above are computed)
NAMES = {
    'nahco3': (_('Sodium bicarbonate'), 'NaHCO₃'), 'na2co3': (_('Sodium carbonate'), 'Na₂CO₃'),
    'naoh': (_('Sodium hydroxide'), 'NaOH'), 'caco3': (_('Calcium carbonate'), 'CaCO₃'),
    'caoh2': (_('Calcium hydroxide'), 'Ca(OH)₂'), 'cao': (_('Calcium oxide'), 'CaO'),
    'co2': (_('Carbon dioxide, added'), 'CO₂'), 'degas': (_('Carbon dioxide, stripped'), '−CO₂'),
    'hcl': (_('Hydrochloric acid'), 'HCl'),
}


@dataclass(frozen=True)
class Reagent:
    """A reagent and its direction on the chart: the DIC (mmol) and the alkalinity (meq) one mmol of it adds; its
    molar mass from the atomic weights (the core's)."""
    key: str
    name: str
    formula: str
    molar_mass: float       # g/mol
    dic: float
    alkalinity: float
    angle: float            # its direction on the chart, 0 to 2π (the source's `radians`)


# The source's REAGENTS, in its order, which is also the order of practicality the recipes are ranked by.
REAGENTS = [Reagent(key, *NAMES[key], molar_mass, dic, alkalinity, angle)
            for key, molar_mass, dic, alkalinity, angle in native.reagents()]
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
    counter_productive: bool = False    # one reagent adds alkalinity and the other takes it away
    priority: int = 0                   # the reagents' places in REAGENTS, summed: the practical first


def split(start, end, first, second):
    """How much of each of two reagents takes the water from `start` to `end` (the core's Cramer's rule): (lower, a,
    higher, b), a and b in mmol/L, `lower` the reagent of the smaller angle; None when they cannot reach it."""
    found = native.split(tuple(start), tuple(end), first.key, second.key)
    if found is None:
        return None
    lower, a, higher, b = found
    return BY_KEY[lower], a, BY_KEY[higher], b


def at_target(start, end):
    """The water is at its target: closer than 0.001 in DIC and in alkalinity (the core's)."""
    return native.at_target(tuple(start), tuple(end))


def recipes(start, end, chosen, volume=None, air=None):
    """The recipes from the water to the target with the chosen reagents (keys), practical ones first, at most
    MAX_RECIPES; none when the water is at the target. `air`: (temperature, salinity, the air's CO₂ in mg/L) to flag
    a recipe whose stripping would end below the air's CO₂ whichever of its doses goes first."""
    return [Recipe([Dose(BY_KEY[key], concentration, grams, delta_dic, delta_alkalinity)
                    for key, concentration, grams, delta_dic, delta_alkalinity in made['doses']],
                   made['waypoint'], made['below_air'], made['counter_productive'], made['priority'])
            for made in native.recipes(tuple(start), tuple(end), list(chosen), volume, air)]


# ---- the dosing layer of the chart ------------------------------------------------------------------------
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


def visual(start, end, chosen):
    """The dosing layer for the chosen reagents (keys, in the order chosen); `end` None without a target."""
    found = native.visual(tuple(start), None if end is None else tuple(end), list(chosen))
    return Visual([(BY_KEY[key], line) for key, line in found['lines']], found['wedge'], found['path'],
                  found['waypoint'], messages.dosing_note(found['note']))


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
    """The water after each amount (grams by reagent key) added in turn to `volume` m³, in REAGENTS' order (the
    source's), from `start` (DIC, alkalinity) at `ph`; a stripping step that takes the CO₂ below `air_co2_mg_l` is
    flagged; [] without an amount (the core's)."""
    return [Step(None if key is None else BY_KEY[key], *rest)
            for key, *rest in native.simulate(eq.temp_c, eq.salinity, tuple(start), ph,
                                              [(key, grams) for key, grams in amounts.items() if grams is not None],
                                              volume, air_co2_mg_l)]
