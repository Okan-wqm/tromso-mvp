"""The calculator (Operations › Water chemistry › Calculator): everything its page shows for one set of
values, worked out once, and the values a unit or a loop offers it. The page, its live parts and its printed
report draw from one `Calculation`, so they never disagree; nothing is stored.

- `calculate`: the analysis of the water (farm/water/deffeyes.py), the Water Quality Management Chart with
  its dosing and simulator layers, the four small charts (farm/water/charts.py), the dosing recipes from
  the water to the target and the simulator's steps (farm/water/dosing.py), each step judged as the water is:
  its pH against the pH bounds, its alkalinity against the band, its CO₂ against the CO₂ limit at its
  alkalinity, its NH₃ and H₂S against their borders.
- `offers`: what a unit or a loop gives the calculator, read from the water module (only through
  farm/water/read.py) and never written back: the latest value of each measured field (read.latest, each with
  its time), the site's altitude, and the limits of the fish in it today (read.limits_now): the critical high of
  NH₃-N and of CO₂ (the calculator has one limit for each and its own 0.2 pH alert band: a species' warning
  bound for them is not used), the warning bounds of the alkalinity as the safe zone's band, and the four pH
  bounds; where several species are in it, the strictest."""
from dataclasses import dataclass, field
from decimal import Decimal

from django.utils.translation import gettext_lazy as _

from ..models.water import site_of
from . import charts, chemistry, deffeyes, dosing, read
from .evaluate import Status, judge as judge_bounds

# The calculator's fields a unit or a loop measures, by the parameter they are.
MEASURED_FIELDS = ['temperature_c', 'ph', 'salinity_ppt', 'alkalinity_mg_l', 'tan_mg_l', 'oxygen_mg_l']
ALTITUDE_HIGH = 5000            # the calculator's altitude field goes from sea level to this (m)
# The pH bounds, the field each fills and how the strictest of several species' is picked.
PH_BOUNDS = [('ph_critical_low', 'critical_low', max), ('ph_warning_low', 'warning_low', max),
             ('ph_warning_high', 'warning_high', min), ('ph_critical_high', 'critical_high', min)]


# ---- the simulator's steps, judged ------------------------------------------------------------------------
@dataclass(frozen=True)
class PhBounds:
    """The pH a water may have (NBS), as the water limits say it: inside the warning bounds ok, outside them a
    warning, outside the critical bounds critical (farm/water/evaluate.py); any bound may be missing."""
    critical_low: float | None = None
    warning_low: float | None = None
    warning_high: float | None = None
    critical_high: float | None = None

    @property
    def given(self):
        return any(bound is not None for bound in (self.critical_low, self.warning_low, self.warning_high,
                                                    self.critical_high))


@dataclass(frozen=True)
class JudgedStep:
    """A step of the simulator with what the water would be there, each value judged."""
    step: dosing.Step
    ph_status: str
    alkalinity_status: str
    co2: deffeyes.Border
    nh3_n_mg_l: float | None
    nh3: deffeyes.Border
    h2s_ug_l: float | None
    h2s: deffeyes.Border

    @property
    def alkalinity_mg_l(self):
        return self.step.alkalinity * chemistry.MG_CACO3_PER_MEQ


def judge_step(analysis, step, ph_bounds=PhBounds()):
    """A simulator step judged as the water is: its pH against the pH bounds, its alkalinity against the band
    (a warning outside it), its CO₂ border at its own alkalinity, its pH against the NH₃ and H₂S borders (which
    do not depend on the alkalinity). A dose can take a water to a pH no fish lives in, with nothing else wrong."""
    eq, limits, ph = analysis.equilibria, analysis.limits, step.ph
    if ph is None:
        none = deffeyes.Border(None, False, None, Status.NOT_MEASURED)
        return JudgedStep(step, Status.NOT_MEASURED, Status.NOT_MEASURED, none, None, none, None, none)
    ph_status = judge_bounds(ph, ph_bounds) if ph_bounds.given else Status.NO_LIMIT
    low, high = limits.alkalinity_low_mg_l, limits.alkalinity_high_mg_l
    alkalinity = step.alkalinity * chemistry.MG_CACO3_PER_MEQ
    alkalinity_status = (Status.NO_LIMIT if low is None or high is None
                         else Status.OK if low <= alkalinity <= high else Status.WARNING)
    co2_limit = None if limits.co2_mg_l is None else limits.co2_mg_l / chemistry.MG_CO2_PER_MMOL
    co2 = deffeyes.judge(ph, None if co2_limit is None else eq.ph_where_co2(step.alkalinity, co2_limit), False,
                         Status.NO_LIMIT if co2_limit is None else None)
    missing = {Status.NOT_MEASURED, Status.NO_LIMIT}
    nh3 = deffeyes.judge(ph, analysis.nh3.ph, True, analysis.nh3.status if analysis.nh3.status in missing else None)
    h2s = deffeyes.judge(ph, analysis.h2s.ph, False, analysis.h2s.status if analysis.h2s.status in missing else None)
    tan, sulfide = analysis.water.tan_mg_l, analysis.water.total_sulfide_ug_l
    return JudgedStep(
        step, ph_status, alkalinity_status, co2, None if tan is None else tan * eq.nh3_share(ph), nh3,
        None if sulfide is None else sulfide * chemistry.H2S_PER_S * eq.h2s_share(ph), h2s)


# ---- one calculation --------------------------------------------------------------------------------------
@dataclass
class Calculation:
    analysis: deffeyes.Analysis
    chart: deffeyes.Chart
    plots: dict                         # key → charts.Drawing, None when it cannot be drawn
    reagents: list                      # the chosen dosing.Reagent, in REAGENTS' order
    volume_m3: float | None
    recipes: list = field(default_factory=list)
    recipes_note: str = ''
    steps: list = field(default_factory=list)       # [JudgedStep], the water first
    steps_note: str = ''
    air_co2_mg_l: float = 0.0

    @property
    def final(self):
        """The simulator's last step that is a water, and the change from the water to it."""
        reached = [judged for judged in self.steps if judged.step.ph is not None]
        return reached[-1] if len(reached) > 1 else None

    @property
    def change(self):
        """From the water to the simulator's last water: pH, alkalinity (meq/L), DIC (mmol/L) and CO₂ (mg/L)."""
        final = self.final
        if final is None:
            return None
        first, last = self.steps[0].step, final.step
        return {'ph': last.ph - first.ph, 'alkalinity': last.alkalinity - first.alkalinity,
                'dic': last.dic - first.dic, 'co2': last.co2_mg_l - first.co2_mg_l}

    @property
    def stopped(self):
        """The simulator's step that is no water (more taken than there is); None when every step is one."""
        return next((judged for judged in self.steps if judged.step.ph is None), None)


def calculate(water, limits, target, pressure, layers, chosen=(), volume=None, amounts=None, all_layers=False,
              ph_bounds=PhBounds()):
    """Everything the calculator shows. `chosen`: the reagents' keys in the order chosen; `amounts`: grams by
    reagent key for the simulator, its steps' pH judged by `ph_bounds`; `all_layers`: draw every layer whatever
    `layers` says (the printed report, as the source's forces its safety overlays)."""
    analysis = deffeyes.analyse(water, limits, target, pressure)
    eq = analysis.equilibria
    start = (analysis.dic, analysis.alkalinity_meq)
    end = None if target is None else (analysis.target_dic, analysis.target_alkalinity_meq)
    air = chemistry.co2_from_air(water.temperature_c, water.salinity_ppt, pressure)

    def below_air(dic, alkalinity):
        ph = eq.ph_at(dic, alkalinity)
        return ph is None or eq.co2(dic, ph) * chemistry.MG_CO2_PER_MMOL < air

    reagents = [reagent for reagent in dosing.REAGENTS if reagent.key in chosen]
    calculation = Calculation(analysis, None, {}, reagents, volume, air_co2_mg_l=air)
    if end is None:
        calculation.recipes_note = _('Give a target pH and alkalinity for the recipes.')
    elif dosing.at_target(start, end):
        calculation.recipes_note = _('The water is at its target.')
    elif len(reagents) < 2:
        calculation.recipes_note = _('A recipe takes two reagents: choose at least two (the Reagents tab).')
    else:
        calculation.recipes = dosing.recipes(start, end, chosen, volume, below_air)
        if not calculation.recipes:
            calculation.recipes_note = _('No two of the chosen reagents reach the target: choose others.')
    if amounts:
        if volume is None:
            calculation.steps_note = _('Give the volume to follow the amounts.')
        else:
            steps = dosing.simulate(eq, start, water.ph, amounts, volume, air)
            calculation.steps = [judge_step(analysis, step, ph_bounds) for step in steps]
    shown = deffeyes.ALL_LAYERS if all_layers else layers
    simulator = [(judged.step.dic, judged.step.alkalinity) for judged in calculation.steps
                 if judged.step.ph is not None]
    calculation.chart = deffeyes.draw(analysis, shown, dosing.visual(start, end, list(chosen)), simulator)
    calculation.plots = {key: charts.draw(plot) for key, plot in charts.plots(analysis).items()}
    return calculation


# ---- what a unit or a loop offers ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Offer:
    """A value a unit or a loop gives a field of the calculator: a reading (with its time and status), the
    site's altitude, or a limit of the fish in it (with the rows it comes from)."""
    field: str
    value: Decimal | None              # None: the fish have no such bound, the field is emptied
    reading: object = None             # read.Reading
    rows: tuple = ()                   # WaterLimit rows


def _strictest(rows, bound, pick):
    values = [getattr(row, bound) for row in rows if getattr(row, bound) is not None]
    return (pick(values), tuple(row for row in rows if getattr(row, bound) is not None)) if values else (None, ())


def offers(point):
    """{field: Offer} of what the point gives the calculator now."""
    found = {}
    water = read.latest([point])[read.key(point)]
    for name in MEASURED_FIELDS:
        reading = water.get(name)
        if reading is not None and reading.value is not None:
            found[name] = Offer(name, reading.value, reading=reading)
    site = site_of(point)
    if site is not None and site.altitude is not None and 0 <= site.altitude <= ALTITUDE_HIGH:
        found['altitude_m'] = Offer('altitude_m', Decimal(round(site.altitude)))
    limits = read.limits_now(point)
    for name, code in (('nh3_n_limit_mg_l', 'nh3_n_mg_l'), ('co2_limit_mg_l', 'co2_mg_l')):
        value, rows = _strictest(limits.get(code, []), 'critical_high', min)
        if value is not None:
            found[name] = Offer(name, value, rows=rows)
    rows = limits.get('ph', [])
    if rows:                           # the fish's bounds are all of them: one they have none of is empty
        for name, bound, pick in PH_BOUNDS:
            value, used = _strictest(rows, bound, pick)
            found[name] = Offer(name, value, rows=used)
    band = limits.get('alkalinity_mg_l', [])
    low, low_rows = _strictest(band, 'warning_low', max)
    high, high_rows = _strictest(band, 'warning_high', min)
    if low is not None and high is not None and low < high:
        found['alkalinity_low_mg_l'] = Offer('alkalinity_low_mg_l', low, rows=low_rows)
        found['alkalinity_high_mg_l'] = Offer('alkalinity_high_mg_l', high, rows=high_rows)
    return found
