"""The calculator (Operations › Water chemistry › Calculator): everything its page shows for one set of
values, worked out once, and the values a unit or a loop offers it. The page, its live parts and its printed
report draw from one `Calculation`, so they never disagree; nothing is stored.

- `calculate`: the analysis of the water (farm/water/deffeyes.py), the Water Quality Management Chart with
  its dosing and simulator layers, the four small charts (farm/water/charts.py), the dosing recipes from
  the water to the target and the simulator's steps (farm/water/dosing.py), each step judged as the water is:
  its pH against the pH bounds, its alkalinity against the band, its CO₂ against the CO₂ limit at its
  alkalinity, its NH₃ and H₂S against their borders.
- `offers`: what a unit or a loop gives the calculator, read from the water module (only through
  farm/water/read.py) and never written back: the latest value of each measured field at the owner's water,
  its middle point (read.unit_water, each with its time; nothing from its loop, as on Production units), the site's
  altitude, and the limits of the fish in it today (read.limits_now): the critical high of
  NH₃-N and of CO₂ (the calculator has one limit for each and its own 0.2 pH alert band: a species' warning
  bound for them is not used), the warning bounds of the alkalinity as the safe zone's band, and the four pH
  bounds; where several species are in it, the strictest.
- `inputs_from`: the one mapping from the calculator's field values to the analysis's water, limits, target and
  pressure; the calculator's form and a unit's chart both call it.
- `chart_of`: a unit's own Deffeyes chart, from the readings of one of its sampling points and the limits of its
  fish, or a `Refusal` that lists what is missing. It never fills a value in: the calculator's example water
  (forms/water.py DEFAULTS) does not reach a unit; the one assumption is a fresh-water unit's salinity of 0, which
  the chart says (read.assumed_salinity)."""
from dataclasses import dataclass, field
from decimal import Decimal

from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from ..models import SamplingPoint, System
from ..models.water_point import site_of
from . import charts, chemistry, deffeyes, dosing, messages, native, parameters, read
from .evaluate import Status, judge as judge_bounds

# The calculator's fields a unit or a loop measures, by the parameter they are.
MEASURED_FIELDS = ['temperature_c', 'ph', 'salinity_ppt', 'alkalinity_mg_l', 'tan_mg_l', 'oxygen_mg_l',
                   'conductivity_25_us_cm', 'hardness_mg_l', 'phosphate_p_mg_l']
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
    alkalinity_mg_l: float | None = None


def judge_step(analysis, step, ph_bounds=PhBounds()):
    """A simulator step judged as the water is (the core's, chemcore/core/src/analysis.rs `judge_step`): its pH against
    the pH bounds, its alkalinity against the band (a warning outside it), its CO₂ border at its own alkalinity, its pH
    against the NH₃ and H₂S borders (which do not depend on the alkalinity). A dose can take a water to a pH no fish
    lives in, with nothing else wrong."""
    if step.ph is None:
        none = deffeyes.Border(None, False, None, Status.NOT_MEASURED)
        return JudgedStep(step, Status.NOT_MEASURED, Status.NOT_MEASURED, none, None, none, None, none)
    ph_status = judge_bounds(step.ph, ph_bounds) if ph_bounds.given else Status.NO_LIMIT
    water, limits, target, pressure = deffeyes._inputs(analysis)
    found = native.judge_step(water, limits, step.ph, step.alkalinity, target, pressure)
    return JudgedStep(
        step, ph_status, Status(found['alkalinity_status']), deffeyes._border(found['co2']), found['nh3_n_mg_l'],
        deffeyes._border(found['nh3']), found['h2s_ug_l'], deffeyes._border(found['h2s']), found['alkalinity_mg_l'])


# ---- the calculator's values as the analysis takes them ---------------------------------------------------
def inputs_from(values):
    """{water, limits, target, pressure} for `calculate` from the calculator's field values (`values`: by field name,
    numbers as floats, a missing optional one None or absent): the water a sample holds, the limits, the target and
    the pressure at the altitude. THE mapping: the calculator's form and a unit's chart both go through it."""
    water = deffeyes.Water(
        temperature_c=values['temperature_c'], salinity_ppt=values['salinity_ppt'], ph=values['ph'],
        alkalinity_mg_l=values['alkalinity_mg_l'], tan_mg_l=values.get('tan_mg_l'),
        total_sulfide_ug_l=values.get('total_sulfide_ug_l'), calcium_mg_l=values.get('calcium_mg_l'),
        oxygen_mg_l=values.get('oxygen_mg_l'), conductivity_25_us_cm=values.get('conductivity_25_us_cm'),
        hardness_mg_l=values.get('hardness_mg_l'), water_origin=values.get('water_origin') or '',
        phosphate_p_mg_l=values.get('phosphate_p_mg_l'))
    limits = deffeyes.Limits(
        nh3_n_mg_l=values.get('nh3_n_limit_mg_l'), co2_mg_l=values.get('co2_limit_mg_l'),
        h2s_ug_l=values.get('h2s_limit_ug_l'), alkalinity_low_mg_l=values.get('alkalinity_low_mg_l'),
        alkalinity_high_mg_l=values.get('alkalinity_high_mg_l'))
    target = None
    if values.get('target_ph') is not None:
        target = deffeyes.Target(values['target_ph'], values['target_alkalinity_mg_l'])
    altitude = values.get('altitude_m')
    return {'water': water, 'limits': limits, 'target': target,
            'pressure': chemistry.pressure_atm(altitude) if altitude is not None else 1.0}


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
    def phosphate_note(self):
        """With a phosphate given, the sentence said beside every recipe and beside the simulator's steps: the phosphate
        they were worked out with, as P and as PO₄, and that a wrong one changes the dose (the independent review of
        2026-11-16, R3: a PO₄ reading typed as P is 3.07 times too much, and nothing beside a dose said it depended on
        the phosphate); '' without one."""
        return messages.phosphate_used(self.analysis.equilibria)

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
              ph_bounds=PhBounds(), plots=True):
    """Everything the calculator shows. `chosen`: the reagents' keys in the order chosen; `amounts`: grams by
    reagent key for the simulator, its steps' pH judged by `ph_bounds`; `all_layers`: draw every layer whatever
    `layers` says (the printed report, as the source's forces its safety overlays); `plots`: the four small charts
    too (a unit's chart leaves them out)."""
    analysis = deffeyes.analyse(water, limits, target, pressure)
    eq = analysis.equilibria
    start = (analysis.dic, analysis.alkalinity_meq)
    end = None if target is None else (analysis.target_dic, analysis.target_alkalinity_meq)
    air = chemistry.co2_from_air(water.temperature_c, water.salinity_ppt, pressure)
    reagents = [reagent for reagent in dosing.REAGENTS if reagent.key in chosen]
    calculation = Calculation(analysis, None, {}, reagents, volume, air_co2_mg_l=air)
    if end is None:
        calculation.recipes_note = _('Give a target pH and alkalinity for the recipes.')
    elif dosing.at_target(start, end):
        calculation.recipes_note = _('The water is at its target.')
    elif len(reagents) < 2:
        calculation.recipes_note = _('A recipe takes two reagents: choose at least two (the Reagents tab).')
    else:
        calculation.recipes = dosing.recipes(start, end, chosen, volume, (eq, air))
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
    if plots:
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


def offers(owner, now=None, point=None, water=None):
    """{field: Offer} of what a unit or a loop gives the calculator now. `point`: a sampling point of the owner whose
    readings are given instead of its middle point's (a unit's inlet, its outlet); nothing is borrowed from any other
    point."""
    found = {}
    if water is None:
        water = read.owner_water([owner], now)[owner.pk] if point is None else read.latest([point], now)[point.pk]
    for name in MEASURED_FIELDS:
        reading = water.get(name)
        if reading is not None and reading.value is not None:
            found[name] = Offer(name, reading.value, reading=reading)
    site = site_of(owner)
    if site is not None and site.altitude is not None:        # the database holds its range (models.site)
        found['altitude_m'] = Offer('altitude_m', Decimal(round(site.altitude)))
    found.update(fish_limits(owner))
    return found


def fish_limits(owner):
    """{field: Offer} of the limits of the fish in a unit or a loop today: the NH₃-N and CO₂ limits, the pH bounds, the
    alkalinity band."""
    found = {}
    limits = read.limits_now(owner)
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


# ---- a unit's own chart ---------------------------------------------------------------------------------------
# What a unit's chart must have, in the order they are listed when missing.
REQUIRED = ['temperature_c', 'ph', 'alkalinity_mg_l', 'salinity_ppt']
OPTIONAL = ['tan_mg_l', 'oxygen_mg_l', 'conductivity_25_us_cm', 'hardness_mg_l', 'phosphate_p_mg_l']
# The limits a unit's chart takes from the fish, by the calculator field they fill.
LIMIT_FIELDS = ['nh3_n_limit_mg_l', 'co2_limit_mg_l', 'alkalinity_low_mg_l', 'alkalinity_high_mg_l']


@dataclass(frozen=True)
class ChartInput:
    """One value a unit's chart is drawn from: a reading (with its sample, age and status), or the assumed salinity
    of fresh water, or the site's altitude."""
    field: str
    label: object
    value: Decimal
    reading: object = None             # read.Reading; None when `assumed` or the altitude
    assumed: bool = False


@dataclass(frozen=True)
class UnitChart:
    """A unit's Deffeyes chart for one of its sampling points: the inputs it was drawn from, the limits of its fish with
    the rows they come from, the calculation, and `absent`, the labels of the limits the fish do not have (so that
    border is missing from the chart)."""
    unit: object
    point: SamplingPoint
    now: object
    inputs: list
    limits: dict                       # calculator field -> Offer
    calculation: Calculation
    assumed: tuple = ()                # the fields that are assumed, never measured: ('salinity_ppt',)
    absent: tuple = ()
    points: tuple = ()                 # the unit's active points, middle first (the window's links)
    sensors_failed: bool = False       # the live values could not be read: the samples alone gave the inputs


@dataclass(frozen=True)
class Refusal:
    """A unit's chart that cannot be drawn, and why: `missing` the labels of the readings the point lacks, `impossible`
    the reason a pH and an alkalinity cannot go together, `no_point` that the unit has no middle point and none was
    chosen; `points` are the unit's active points, to choose another."""
    unit: object
    point: SamplingPoint | None
    missing: list
    points: tuple = ()
    impossible: str = ''
    no_point: bool = False
    sensors_failed: bool = False


def chart_of(unit, point=None, now=None, at=None):
    """The Deffeyes chart (UnitChart) of a unit's or a system's water at `point` (one of its sampling points; the middle
    point by default, a system's loop), or a Refusal; with `at`, as the water was at that past moment (read.latest: the
    samples and the sensor values of then, their age relative to it). The temperature, pH, alkalinity and salinity are the point's own latest readings (a
    sea unit without a salinity is refused; a fresh-water unit's is 0, said); the TAN and the oxygen are drawn when
    they are there; the sulfide and the calcium are measured nowhere, so there is no H2S or calcite layer. The limits
    are the fish's (`offers`). Never a default: what is missing is listed."""
    now = at or now or timezone.now()
    points = points_for(unit)
    if point is None:
        point = next((each for each in points if each.kind == read.MIDDLE), None)
        if point is None:
            return Refusal(unit, None, [], points, no_point=True)
    water = read.latest([point], at=at)[point.pk] if at is not None else read.latest([point], now)[point.pk]
    failed = water.sensors_failed
    found = offers(unit, now, point, water)
    values = {name: float(found[name].value) for name in (*REQUIRED, *OPTIONAL) if name in found}
    inputs = {name: ChartInput(name, parameters.get(name).label, found[name].value, found[name].reading)
              for name in (*REQUIRED, *OPTIONAL) if name in found}
    assumed = ()
    if 'salinity_ppt' not in found:
        salinity = read.assumed_salinity(_water_types(unit))
        if salinity is not None:
            values['salinity_ppt'] = float(salinity)
            inputs['salinity_ppt'] = ChartInput('salinity_ppt', parameters.get('salinity_ppt').label, salinity,
                                                assumed=True)
            assumed = ('salinity_ppt',)
    missing = [parameters.get(name).label for name in REQUIRED if name not in values]
    if missing:
        return Refusal(unit, point, missing, points, sensors_failed=failed)
    values['water_origin'] = origin_of(unit)
    why = deffeyes.why_impossible(values['temperature_c'], values['salinity_ppt'], values['ph'],
                                  values['alkalinity_mg_l'], **ions_of(values))
    if why:
        return Refusal(unit, point, [], points, impossible=why, sensors_failed=failed)
    if 'altitude_m' in found:
        values['altitude_m'] = float(found['altitude_m'].value)
        inputs['altitude_m'] = ChartInput('altitude_m', _('Altitude (m)'), found['altitude_m'].value)
    limits = chart_limits(found)
    values.update({name: float(offer.value) for name, offer in limits.items()})
    made = calculate(**inputs_from(values), layers=deffeyes.ALL_LAYERS, plots=False)
    absent = tuple(label for name, label in (('nh3_n_limit_mg_l', _('NH₃-N limit')), ('co2_limit_mg_l', _('CO₂ limit')))
                   if name not in limits)
    ordered = [inputs[name] for name in (*REQUIRED, *OPTIONAL, 'altitude_m') if name in inputs]
    return UnitChart(unit, point, now, ordered, limits, made, assumed, absent, points, sensors_failed=failed)


def ions_of(values):
    """The conductivity at 25 °C and the hardness of field values (None when absent), and the water's origin ('' not
    said): what a water's equilibria read besides its alkalinity and salinity (formula 3)."""
    return {**{name: values.get(name) for name in ('conductivity_25_us_cm', 'hardness_mg_l', 'phosphate_p_mg_l')},
            'water_origin': values.get('water_origin') or ''}


def chart_limits(offered):
    """{field: Offer} of the limits a unit's chart is drawn with (LIMIT_FIELDS), of those offered."""
    return {name: offered[name] for name in LIMIT_FIELDS if name in offered}


def points_for(owner):
    """The active points of a unit (its middle point first) or of a system (its loop first)."""
    if isinstance(owner, System):
        found = SamplingPoint.objects.filter(system=owner, is_active=True).with_owners()
        return tuple(sorted(found, key=lambda point: (point.kind != read.MIDDLE, point.name)))
    return tuple(read.points_of([owner])[owner.pk])


def origin_of(owner):
    """Where the salt of a unit's, a system's or a sampling point's water comes from (read.common_origin of its units, a
    point's those it serves as its samples' NH3 takes them; '' not said)."""
    return read.common_origin(_units_of(owner))


def scale_origin_of(owner):
    """The origin of a unit's, a system's or a sampling point's water for the pH-scale rule (read.scale_origin of the
    same units: salt added as soon as one of them says so)."""
    return read.scale_origin(_units_of(owner))


def _units_of(owner):
    """The units whose water a unit, a system or a sampling point is (a point's: those it serves)."""
    if isinstance(owner, SamplingPoint):
        return read.Context._served([owner])[owner.pk]
    return list(owner.tanks.all()) if isinstance(owner, System) else [owner]


def _water_types(owner):
    """The water types the owner's water is in: a unit's own, a system's units' (none: nothing is assumed)."""
    if isinstance(owner, System):
        return {unit.water_type for unit in owner.tanks.all()} or {None}
    return {owner.water_type}
