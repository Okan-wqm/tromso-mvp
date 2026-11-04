"""The Water Quality Management Chart: a Deffeyes diagram (Deffeyes 1965, Limnol. Oceanogr. 10: 412) of a
water, its alkalinity against its dissolved inorganic carbon, with the lines of equal pH, the regions where
CO₂, NH₃ and H₂S exceed their limits, the safe region, the calcite and aragonite saturation lines and the
water's point. Ported from the source's calculator (/sites/water-chemistry, the Calculator tab:
libs/aquaculture-engines/src/water-chemistry/deffeyes-data.ts, web/shared-ui/src/water-chemistry/compute.ts
and components/DeffeyesChart.tsx); the chemistry is farm/water/chemistry.py. Pure Python, no database:
`analyse` works out the values of a water (`Water`, what a sample holds) against `Limits` and an optional
`Target`, `geometry` lays the chart out in the chart's own units, and `draw` turns it into the SVG that
templates/farm/_deffeyes_chart.html shows, server-rendered, without JavaScript.

The calculator (Operations › Water chemistry › Calculator) fills `Water`, `Limits` and `Target` from its
form; a unit's own chart (calculation.chart_of, the monitoring cards' window) fills `Water` from its latest
readings and `Limits` from the water limits of its fish, through the same `calculation.inputs_from`; nothing
here changes for either (README, Water chemistry).

What the chart shows, as the source draws it (the corrections are in the bug document, WQ-30 to WQ-39):
- Axes: DIC (mmol/L) across, alkalinity (meq/L) up, 0 to 6 each; wider when the water's point, the
  target or the alkalinity band lies beyond (WQ-33).
- pH isolines every 0.25 from 4.25 to 12.5, straight lines (chemistry.Equilibria.isoline); those every
  0.5 from 5.0 to 12.0 stronger and labelled.
- NH₃ toxic: above the isoline of the pH where the TAN gives the NH₃-N limit. H₂S toxic: below the
  isoline of the pH where the total sulfide gives the H₂S limit. CO₂ toxic: below (right of) the curve
  where CO₂ equals the limit, DIC α0 = c. Each is shaded, its boundary dashed.
- The safe zone: the alkalinity band (low to high) between the NH₃ isoline and the CO₂ curve or the H₂S
  isoline, whichever is the higher pH (WQ-30). A missing value is never taken for a safe one: without the
  TAN, the NH₃ limit or the CO₂ limit, or with a total sulfide but no H₂S limit, there is no safe zone and a
  note says what is missing; without a total sulfide the zone is drawn and named "H₂S not assessed".
- Ω = 1 for calcite and aragonite (Mucci 1983) for the calcium given, in water of 5 to 44 ‰ (WQ-32).
- The water (a star) and the target (a cross), a dashed line between them.
- A limit's status follows the source: past its pH border critical, within 0.2 pH of it a warning. A
  border outside the chart's pH range (4 to 12.5) is said in words, not as a number (WQ-34); its region is
  still shaded wherever it meets the plotted box, which in a large box can reach past pH 12.5 or below 4.
- Dosing (farm/water/dosing.py, as `dosing.Visual`): one reagent chosen, its direction line from the water;
  two, both lines, the wedge between them and their path to the target through the waypoint. The simulator:
  the water after each amount, joined from the water, an arrowhead at each step. The axes grow to hold the
  waypoint and every step."""
import math
from dataclasses import dataclass, field
from decimal import Decimal

from django.utils import formats
from django.utils.translation import gettext_lazy as _

from . import chemistry
from .evaluate import Status

PH_RANGE = (4.0, 12.5)                                       # the chart's pH domain (the source's)
ISOLINE_PHS = [round(4.25 + 0.25 * step, 2) for step in range(34)]
LABELLED_PHS = {round(5.0 + 0.5 * step, 1) for step in range(15)}
AXIS = 6                      # the axes' ends at least: 6 mmol/L DIC and 6 meq/L alkalinity
ALERT_PH = 0.2                # a pH border nearer than this is a warning
OMEGA_SALINITY = (5, 44)      # the salinities Mucci (1983) measured
SAMPLES = 96                  # points along a curve

LAYERS = [
    ('isolines', _('pH isolines')),
    ('safe', _('Safe zone')),
    ('nh3', _('NH₃ toxic')),
    ('co2', _('CO₂ toxic')),
    ('h2s', _('H₂S toxic')),
    ('omega', _('Ω calcite and aragonite')),
    ('target', _('Target')),
    ('dosing', _('Dosing path')),
    ('simulator', _('Simulator path')),
]
ALL_LAYERS = frozenset(key for key, _label in LAYERS)


# ---- what goes in ----------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Water:
    """The water the chart is drawn for: what a sample holds. Units and bases are in the names; total
    sulfide is as S."""
    temperature_c: float
    salinity_ppt: float
    ph: float
    alkalinity_mg_l: float
    tan_mg_l: float | None = None
    total_sulfide_ug_l: float | None = None
    calcium_mg_l: float | None = None
    oxygen_mg_l: float | None = None


@dataclass(frozen=True)
class Limits:
    """The values not to pass: NH₃-N in mg/L as N, CO₂ in mg/L, H₂S in µg/L as H₂S; and the alkalinity band
    the safe zone lies in, mg/L as CaCO₃. Any of them may be missing."""
    nh3_n_mg_l: float | None = None
    co2_mg_l: float | None = None
    h2s_ug_l: float | None = None
    alkalinity_low_mg_l: float | None = None
    alkalinity_high_mg_l: float | None = None


@dataclass(frozen=True)
class Target:
    ph: float
    alkalinity_mg_l: float


# ---- what comes out ----------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Border:
    """A limit as a pH: toxic above `ph` (NH₃) or below it (CO₂, H₂S); `ph` None when the limit cannot be
    reached. `margin` is how far the water's pH is from it on the safe side (negative: past it)."""
    ph: float | None
    toxic_above: bool
    margin: float | None
    status: str

    @property
    def on_chart(self):
        """The border is a pH of the chart's range (4 to 12.5): it is shown as a number."""
        return self.ph is not None and PH_RANGE[0] <= self.ph <= PH_RANGE[1]

    @property
    def everywhere(self):
        """The limit is passed at every pH of the chart's range (the border lies beyond it on the toxic side)."""
        if self.ph is None:
            return False
        return self.ph < PH_RANGE[0] if self.toxic_above else self.ph > PH_RANGE[1]

    @property
    def off_chart(self):
        """The limit is not reached at any pH of the chart's range (the border lies beyond it on the safe side)."""
        return self.ph is not None and not self.on_chart and not self.everywhere


def judge(ph, border, toxic_above, missing=None):
    """The border and the status: critical past it, a warning within ALERT_PH of it, ok short of it or when
    it cannot be reached. `missing`: the status when there is nothing to judge (no value or no limit)."""
    if missing is not None:
        return Border(None, toxic_above, None, missing)
    if border is None:
        return Border(None, toxic_above, None, Status.OK)
    margin = border - ph if toxic_above else ph - border
    status = Status.CRITICAL if margin <= 0 else Status.WARNING if margin <= ALERT_PH else Status.OK
    return Border(border, toxic_above, margin, status)


@dataclass(frozen=True)
class Analysis:
    """The values of a water, worked out: concentrations per litre, alkalinity in meq/L, DIC in mmol/L."""
    water: Water
    limits: Limits
    target: Target | None
    equilibria: chemistry.Equilibria
    alkalinity_meq: float
    dic: float
    co2_mg_l: float
    co2: Border
    target_alkalinity_meq: float | None
    target_dic: float | None
    target_co2_mg_l: float | None
    nh3_n_mg_l: float | None
    nh3: Border
    safe_tan_mg_l: float | None              # the TAN that gives the NH₃-N limit at this pH
    nh3_share_at_border_pct: float | None    # NH₃ as a share of TAN at the border, limit ÷ TAN
    h2s_ug_l: float | None                   # as H₂S
    h2s: Border
    safe_total_sulfide_ug_l: float | None    # as S: the total sulfide that gives the H₂S limit at this pH
    oxygen_solubility_mg_l: float
    oxygen_saturation_pct: float | None
    pressure_atm: float

    @property
    def nh3_share_pct(self):
        """NH₃ as a share of TAN at the water's pH, in %."""
        return 100 * self.equilibria.nh3_share(self.water.ph)

    @property
    def h2s_share_pct(self):
        """H₂S as a share of the total sulfide at the water's pH, in %."""
        return 100 * self.equilibria.h2s_share(self.water.ph)


def analyse(water, limits=Limits(), target=None, pressure=1.0):
    """The values of a water against the limits: DIC and CO₂ from the alkalinity and the pH, NH₃-N from the
    TAN, H₂S from the total sulfide, each limit as a pH border, the oxygen saturation at `pressure` (atm)."""
    eq = chemistry.equilibria(water.temperature_c, water.salinity_ppt)
    ph = water.ph
    alkalinity = water.alkalinity_mg_l / chemistry.MG_CACO3_PER_MEQ
    dic = eq.dic(alkalinity, ph)
    co2_limit = None if limits.co2_mg_l is None else limits.co2_mg_l / chemistry.MG_CO2_PER_MMOL
    co2 = judge(ph, None if co2_limit is None else eq.ph_where_co2(alkalinity, co2_limit), False,
                Status.NO_LIMIT if co2_limit is None else None)

    target_alkalinity = target_dic = target_co2 = None
    if target is not None:
        target_alkalinity = target.alkalinity_mg_l / chemistry.MG_CACO3_PER_MEQ
        target_dic = eq.dic(target_alkalinity, target.ph)
        target_co2 = eq.co2(target_dic, target.ph) * chemistry.MG_CO2_PER_MMOL

    tan, nh3_limit = water.tan_mg_l, limits.nh3_n_mg_l
    nh3_share = eq.nh3_share(ph)
    nh3 = judge(ph, None if tan is None or nh3_limit is None else eq.ph_where_nh3(tan, nh3_limit), True,
                Status.NOT_MEASURED if tan is None else Status.NO_LIMIT if nh3_limit is None else None)

    sulfide, h2s_limit = water.total_sulfide_ug_l, limits.h2s_ug_l
    h2s_share = eq.h2s_share(ph)
    total_h2s = None if sulfide is None else sulfide * chemistry.H2S_PER_S
    h2s = judge(ph, None if total_h2s is None or h2s_limit is None else eq.ph_where_h2s(total_h2s, h2s_limit),
                False, Status.NOT_MEASURED if sulfide is None else Status.NO_LIMIT if h2s_limit is None else None)

    solubility = chemistry.oxygen_solubility(water.temperature_c, water.salinity_ppt, pressure)
    return Analysis(
        water=water, limits=limits, target=target, equilibria=eq,
        alkalinity_meq=alkalinity, dic=dic, co2_mg_l=eq.co2(dic, ph) * chemistry.MG_CO2_PER_MMOL, co2=co2,
        target_alkalinity_meq=target_alkalinity, target_dic=target_dic, target_co2_mg_l=target_co2,
        nh3_n_mg_l=None if tan is None else tan * nh3_share, nh3=nh3,
        safe_tan_mg_l=None if nh3_limit is None else nh3_limit / nh3_share,
        nh3_share_at_border_pct=None if nh3.ph is None else 100 * nh3_limit / tan,
        h2s_ug_l=None if total_h2s is None else total_h2s * h2s_share, h2s=h2s,
        safe_total_sulfide_ug_l=None if h2s_limit is None else h2s_limit / h2s_share / chemistry.H2S_PER_S,
        oxygen_solubility_mg_l=solubility,
        oxygen_saturation_pct=None if water.oxygen_mg_l is None else 100 * water.oxygen_mg_l / solubility,
        pressure_atm=pressure)


def alkalinity_floor(temperature_c, salinity_ppt, ph):
    """The alkalinity (mg/L as CaCO₃) a water of this pH has at least: hydroxide and borate are alkalinity too, so
    at a high pH the alkalinity has a floor, below which the DIC would be negative."""
    return (chemistry.equilibria(float(temperature_c), float(salinity_ppt)).isoline(float(ph))[1]
            * chemistry.MG_CACO3_PER_MEQ)


def why_impossible(temperature_c, salinity_ppt, ph, alkalinity_mg_l):
    """Why a water of this pH and alkalinity cannot be (its alkalinity at or below the floor of `alkalinity_floor`),
    in the active language; '' when it can. The calculator's form and a unit's chart ask here."""
    floor = alkalinity_floor(temperature_c, salinity_ppt, ph)
    if float(alkalinity_mg_l) > floor:
        return ''
    return str(_('At this pH the alkalinity is above %(floor)s mg/L as CaCO₃: the hydroxide and borate alone are '
                 'that much.') % {'floor': shown(floor, 1)})


def possible(temperature_c, salinity_ppt, ph, alkalinity_mg_l):
    """Whether a water of this pH and alkalinity can be (`why_impossible` has nothing to say)."""
    return not why_impossible(temperature_c, salinity_ppt, ph, alkalinity_mg_l)


# ---- the chart in its own units: DIC (mmol/L) across, alkalinity (meq/L) up --------------------------------
@dataclass(frozen=True)
class Box:
    """The axes' ends and their tick steps."""
    dic: float
    alkalinity: float
    dic_step: float
    alkalinity_step: float

    def corners(self):
        return [(0.0, 0.0), (self.dic, 0.0), (self.dic, self.alkalinity), (0.0, self.alkalinity)]

    def inside(self, point, slack=1e-9):
        x, y = point
        return -slack <= x <= self.dic + slack and -slack <= y <= self.alkalinity + slack


def _axis(needed):
    """The end of an axis and its step: AXIS when the values fit in it with 10 % to spare, else the next
    multiple of a 1-2-5 step that keeps at most 12 ticks."""
    needed *= 1.1
    if needed <= AXIS:
        return float(AXIS), 1.0
    steps = (base * 10 ** power for power in range(8) for base in (1, 2, 5))
    step = next(step for step in steps if needed / step <= 12)
    return math.ceil(needed / step) * step, float(step)


def box_of(analysis, extra=()):
    """The box that holds the water, the target, the alkalinity band and the `extra` points (DIC,
    alkalinity) with 10 % to spare."""
    dics = [analysis.dic, analysis.target_dic or 0, *(point[0] for point in extra)]
    alkalinities = [analysis.alkalinity_meq, analysis.target_alkalinity_meq or 0, *(point[1] for point in extra)]
    if analysis.limits.alkalinity_high_mg_l is not None:
        alkalinities.append(analysis.limits.alkalinity_high_mg_l / chemistry.MG_CACO3_PER_MEQ)
    dic, dic_step = _axis(max(dics))
    alkalinity, alkalinity_step = _axis(max(alkalinities))
    return Box(dic, alkalinity, dic_step, alkalinity_step)


def _clip(polygon, inside):
    """Sutherland–Hodgman: the part of a polygon where the linear function `inside` is ≥ 0."""
    kept = []
    for index, current in enumerate(polygon):
        previous = polygon[index - 1]
        now, before = inside(current), inside(previous)
        if now >= 0:
            if before < 0:
                kept.append(_cross(previous, current, before, now))
            kept.append(current)
        elif before >= 0:
            kept.append(_cross(previous, current, before, now))
    return kept


def _cross(start, end, at_start, at_end):
    share = at_start / (at_start - at_end)
    return start[0] + share * (end[0] - start[0]), start[1] + share * (end[1] - start[1])


def clip_to_box(polygon, box):
    for inside in (lambda p: p[0], lambda p: box.dic - p[0], lambda p: p[1], lambda p: box.alkalinity - p[1]):
        if not polygon:
            break
        polygon = _clip(polygon, inside)
    return polygon if len(polygon) >= 3 else []


def clip_segment(start, end, box):
    """Liang–Barsky: the part of a segment inside the box, or None."""
    low, high = 0.0, 1.0
    dx, dy = end[0] - start[0], end[1] - start[1]
    for p, q in ((-dx, start[0]), (dx, box.dic - start[0]), (-dy, start[1]), (dy, box.alkalinity - start[1])):
        if p == 0:
            if q < 0:
                return None
            continue
        ratio = q / p
        if p < 0:
            low = max(low, ratio)
        else:
            high = min(high, ratio)
        if low > high:
            return None
    if high - low < 1e-12:
        return None
    return (start[0] + low * dx, start[1] + low * dy), (start[0] + high * dx, start[1] + high * dy)


def clip_polyline(points, box):
    """The parts of a polyline inside the box: a list of polylines."""
    lines = []
    for start, end in zip(points, points[1:]):
        part = clip_segment(start, end, box)
        if part is None:
            continue
        if lines and math.dist(lines[-1][-1], part[0]) < 1e-9:
            lines[-1].append(part[1])
        else:
            lines.append([part[0], part[1]])
    return lines


@dataclass(frozen=True)
class Isoline:
    ph: float
    labelled: bool
    segment: tuple           # its two ends inside the box


@dataclass
class Geometry:
    """The chart in DIC (mmol/L) and alkalinity (meq/L): what `draw` maps to the SVG."""
    box: Box
    isolines: list = field(default_factory=list)
    regions: dict = field(default_factory=dict)        # layer → polygon
    boundaries: dict = field(default_factory=dict)     # layer → [polyline]
    omega: dict = field(default_factory=dict)          # 'calcite' / 'aragonite' → [polyline]
    point: tuple = (0.0, 0.0)
    target: tuple | None = None
    reagent_lines: list = field(default_factory=list)  # [(reagent, [polyline])]
    wedge: list = field(default_factory=list)          # polygon
    dosing_path: list = field(default_factory=list)    # [polyline]
    waypoint: tuple | None = None
    simulator: list = field(default_factory=list)      # [(DIC, alkalinity)] of every step, the water first
    notes: list = field(default_factory=list)


def _isoline_segment(eq, ph, box):
    slope, intercept = eq.isoline(ph)
    return clip_segment((0.0, intercept), (box.dic, slope * box.dic + intercept), box)


def _half(eq, ph, box, above):
    """The part of the box above (higher pH) or below a pH's isoline."""
    slope, intercept = eq.isoline(ph)
    sign = 1 if above else -1
    return clip_to_box(_clip(box.corners(), lambda p: sign * (p[1] - slope * p[0] - intercept)), box)


def co2_curve(eq, co2, box):
    """The curve where CO₂ = `co2` (mmol/L) inside the box, from where it enters at alkalinity 0 to where it
    leaves at the top or the right, each point on it: [(DIC, alkalinity)], and whether it leaves at the top.
    Along it the pH and the alkalinity rise with the DIC. ([], False) when it does not cross the box."""
    def alkalinity_at(dic):
        return eq.alkalinity(dic, eq.ph_where_co2_at_dic(dic, co2))

    if co2 >= box.dic or alkalinity_at(box.dic) <= 0:
        return [], False
    start = chemistry.solve(alkalinity_at, co2 * (1 + 1e-9), box.dic)
    leaves_top = alkalinity_at(box.dic) > box.alkalinity
    stop = chemistry.solve(lambda dic: alkalinity_at(dic) - box.alkalinity, start, box.dic) if leaves_top else box.dic
    points = [(start, 0.0)]
    for step in range(1, SAMPLES):
        dic = start + (stop - start) * step / SAMPLES
        points.append((dic, alkalinity_at(dic)))
    points.append((stop, box.alkalinity if leaves_top else alkalinity_at(stop)))
    return points, leaves_top


def _co2_region(curve, leaves_top, box):
    corners = [(box.dic, box.alkalinity)] if leaves_top else []
    return [*curve, *corners, (box.dic, 0.0)]


def safe_zone_gaps(analysis):
    """Why there can be no safe zone, as notes: a missing value is never taken for a safe one. Every limit the
    zone is bounded by must be judged: the TAN and its NH₃ limit, the CO₂ limit, the alkalinity band, and an
    H₂S limit when a total sulfide is given. A water without a total sulfide is not a gap: its zone is drawn,
    named "H₂S not assessed"."""
    limits, gaps = analysis.limits, []
    if limits.alkalinity_low_mg_l is None or limits.alkalinity_high_mg_l is None:
        gaps.append(_('Safe zone: not drawn without the alkalinity band.'))
    elif limits.alkalinity_low_mg_l >= limits.alkalinity_high_mg_l:
        gaps.append(_('Safe zone: not drawn, the alkalinity band is empty (its high end is not above its low end).'))
    if analysis.nh3.status == Status.NOT_MEASURED:
        gaps.append(_('Safe zone: not drawn without the TAN.'))
    elif analysis.nh3.status == Status.NO_LIMIT:
        gaps.append(_('Safe zone: not drawn without the NH₃ limit.'))
    if analysis.co2.status == Status.NO_LIMIT:
        gaps.append(_('Safe zone: not drawn without the CO₂ limit.'))
    if analysis.h2s.status == Status.NO_LIMIT:
        gaps.append(_('Safe zone: not drawn without the H₂S limit, a total sulfide being given.'))
    return gaps


def h2s_assessed(analysis):
    """Whether the safe zone takes H₂S into account: a total sulfide was given."""
    return analysis.h2s.status != Status.NOT_MEASURED


def safe_zone(analysis, box):
    """The safe region: the alkalinity band, from the NH₃ isoline (the highest pH allowed; the chart's top pH
    when the TAN cannot reach its limit) to the CO₂ curve or the H₂S isoline, whichever is the higher pH.
    [] when a value or a limit it needs is missing (safe_zone_gaps), or when the band has no safe pH."""
    if safe_zone_gaps(analysis):
        return []
    limits, eq = analysis.limits, analysis.equilibria
    low = limits.alkalinity_low_mg_l / chemistry.MG_CACO3_PER_MEQ
    high = limits.alkalinity_high_mg_l / chemistry.MG_CACO3_PER_MEQ
    top = analysis.nh3.ph if analysis.nh3.ph is not None else PH_RANGE[1]
    co2 = limits.co2_mg_l / chemistry.MG_CO2_PER_MMOL
    h2s = analysis.h2s.ph

    def co2_alkalinity(ph):
        """The alkalinity whose CO₂ border is this pH: the CO₂ curve's point on the pH's isoline."""
        return eq.alkalinity(co2 / eq.fractions(ph)[0], ph)

    def floor(alkalinity):
        floors = [PH_RANGE[0]]
        border = eq.ph_where_co2(alkalinity, co2)
        if border is not None:
            floors.append(border)
        if h2s is not None:
            floors.append(h2s)
        return max(floors)

    rows = {low + (high - low) * step / (SAMPLES // 2) for step in range(SAMPLES // 2 + 1)}
    closes = co2_alkalinity(top)                   # the CO₂ border meets the NH₃ border here
    rows |= {alkalinity for alkalinity in (closes, co2_alkalinity(h2s) if h2s is not None else None)
             if alkalinity is not None and low < alkalinity < high}
    rows = sorted(row for row in rows if row <= closes and (floor(row) < top or row == closes))
    if len(rows) < 2:
        return []
    left = [(eq.dic(row, top), row) for row in rows]
    right = [(eq.dic(row, top if row == closes else floor(row)), row) for row in reversed(rows)]
    return clip_to_box(left + right, box)


def omega_line(eq, calcium_mg_l, ksp, box):
    """The line Ω = 1 (calcium × carbonate = Ksp) inside the box: for each DIC the pH where its carbonate is
    Ksp ÷ calcium, from just above that carbonate (the source's start) to the box's right edge."""
    carbonate = ksp / (calcium_mg_l / chemistry.MG_CALCIUM_PER_MOL) * 1000      # mmol/L
    start = max(carbonate + 0.01, 0.05)
    if start >= box.dic:
        return []
    points = []
    for step in range(SAMPLES + 1):
        dic = start + (box.dic - start) * step / SAMPLES
        ph = eq.ph_where_carbonate(dic, carbonate)
        if ph is not None:
            points.append((dic, eq.alkalinity(dic, ph)))
    return clip_polyline(points, box)


def geometry(analysis, layers=ALL_LAYERS, dosing=None, simulator=()):
    """The chart of an analysis, the layers asked for, in the chart's units; a note says why a layer asked
    for is not drawn. `dosing`: the dosing layer (a dosing.Visual); `simulator`: the water after each step of
    the simulator, (DIC, alkalinity), the water first."""
    eq, limits, water = analysis.equilibria, analysis.limits, analysis.water
    show_target = 'target' in layers and analysis.target is not None
    path = dosing is not None and 'dosing' in layers and show_target and bool(dosing.path)
    simulator = list(simulator) if 'simulator' in layers and len(simulator) > 1 else []
    box = box_of(analysis, [*simulator, *([dosing.waypoint] if path else [])])
    shape = Geometry(box, point=(analysis.dic, analysis.alkalinity_meq))
    if 'isolines' in layers:
        for ph in ISOLINE_PHS:
            segment = _isoline_segment(eq, ph, box)
            if segment is not None:
                shape.isolines.append(Isoline(ph, ph in LABELLED_PHS, segment))
    if 'nh3' in layers:
        _toxic_region(shape, eq, 'nh3', analysis.nh3, above=True, note=_nh3_note(analysis))
    if 'co2' in layers:
        if limits.co2_mg_l is not None:
            curve, leaves_top = co2_curve(eq, limits.co2_mg_l / chemistry.MG_CO2_PER_MMOL, box)
            if curve:
                shape.regions['co2'] = clip_to_box(_co2_region(curve, leaves_top, box), box)
                shape.boundaries['co2'] = [curve]
        else:
            shape.notes.append(_('CO₂: no limit given.'))
    if 'h2s' in layers:
        _toxic_region(shape, eq, 'h2s', analysis.h2s, above=False, note=_h2s_note(analysis))
    if 'safe' in layers:
        gaps = safe_zone_gaps(analysis)
        zone = safe_zone(analysis, box)
        if gaps:
            shape.notes.extend(gaps)
        elif zone:
            shape.regions['safe'] = zone
            if not h2s_assessed(analysis):
                shape.notes.append(_('Safe zone: H₂S not assessed, no total sulfide given.'))
        else:
            shape.notes.append(_('Safe zone: no pH in the alkalinity band is inside every limit.'))
    if 'omega' in layers:
        if water.calcium_mg_l and OMEGA_SALINITY[0] <= water.salinity_ppt <= OMEGA_SALINITY[1]:
            shape.omega['calcite'] = omega_line(eq, water.calcium_mg_l, eq.ksp_calcite, box)
            shape.omega['aragonite'] = omega_line(eq, water.calcium_mg_l, eq.ksp_aragonite, box)
        else:
            shape.notes.append(_('Ω: needs the calcium and a salinity of 5 to 44 ‰, the range of Mucci (1983).'))
    if show_target:
        shape.target = (analysis.target_dic, analysis.target_alkalinity_meq)
    if dosing is not None and 'dosing' in layers:
        for reagent, line in dosing.lines:
            shape.reagent_lines.append((reagent, clip_polyline(line, box)))
        shape.wedge = clip_to_box(dosing.wedge, box) if dosing.wedge else []
        if path:
            shape.dosing_path = clip_polyline(dosing.path, box)
            shape.waypoint = dosing.waypoint
        if dosing.note:
            shape.notes.append(dosing.note)
    shape.simulator = simulator
    return shape


def _toxic_region(shape, eq, key, border, above, note):
    """The region past a limit's border (above its isoline for NH₃, below for H₂S), shaded from the real
    border wherever it meets the plotted box, whether or not the border is inside the chart's pH range: a
    large box reaches past pH 12.5 or below 4. The note when there is nothing to shade."""
    region = _half(eq, border.ph, shape.box, above=above) if border.ph is not None else []
    if region:
        shape.regions[key] = region
        segment = _isoline_segment(eq, border.ph, shape.box)
        shape.boundaries[key] = [list(segment)] if segment else []
    else:
        shape.notes.append(note)


def _nh3_note(analysis):
    if analysis.nh3.status == Status.NOT_MEASURED:
        return _('NH₃: give the TAN.')
    if analysis.nh3.status == Status.NO_LIMIT:
        return _('NH₃: no limit given.')
    if analysis.nh3.ph is not None:
        return _('NH₃: the limit is not reached anywhere on this chart.')
    return _('NH₃: the TAN cannot give the limit at any pH (the limit is not below the TAN).')


def _h2s_note(analysis):
    if analysis.h2s.status == Status.NOT_MEASURED:
        return _('H₂S: give the total sulfide.')
    if analysis.h2s.status == Status.NO_LIMIT:
        return _('H₂S: no limit given.')
    if analysis.h2s.ph is not None:
        return _('H₂S: the limit is not reached anywhere on this chart.')
    return _('H₂S: the total sulfide cannot give the limit at any pH.')


# ---- the SVG --------------------------------------------------------------------------------------------
WIDTH, HEIGHT = 600, 600
LEFT, TOP, PLOT = 64, 16, 520                 # the plot is a square of PLOT px
LABEL_AT = 0.52                               # an isoline's label sits this far along it (the source's)
# The isolines' colours, the source's sequential ramp (shared-contracts domainScale.sequential, read by
# phIsolineColor in deffeyes-data.ts): one step per half pH unit from 5.5, red to deep purple; below pH 6.0
# the first, from 10.0 up the last.
RAMP = ['#DC2626', '#EF4444', '#F97316', '#EAB308', '#22C55E', '#06B6D4', '#3B82F6', '#6366F1', '#A855F7',
        '#7C3AED']


def isoline_colour(ph):
    return RAMP[min(len(RAMP) - 1, max(0, math.floor((ph - 5.5) / 0.5)))]


def _fixed(value):
    return f'{value:.2f}'


@dataclass
class Chart:
    """The SVG's parts in pixels, every coordinate a string with a dot decimal whatever the language: the
    template prints them as they are."""
    width: int
    height: int
    plot: dict
    x_ticks: list
    y_ticks: list
    isolines: list
    regions: list
    boundaries: list
    omega: list
    legend: list
    point: dict
    target: dict | None
    path: str | None
    notes: list
    box: Box
    reagent_lines: list = field(default_factory=list)
    wedge: str | None = None
    dosing_path: list = field(default_factory=list)
    waypoint: dict | None = None
    simulator: dict | None = None


def draw(analysis, layers=ALL_LAYERS, dosing=None, simulator=()):
    """The chart of an analysis as the template draws it (`dosing` and `simulator` as `geometry` takes them)."""
    shape = geometry(analysis, layers, dosing, simulator)
    box = shape.box

    def x(dic):
        return LEFT + dic / box.dic * PLOT

    def y(alkalinity):
        return TOP + PLOT - alkalinity / box.alkalinity * PLOT

    def points(polyline):
        return ' '.join(f'{_fixed(x(dic))},{_fixed(y(alkalinity))}' for dic, alkalinity in polyline)

    def ticks(end, step, place):
        return [{'at': _fixed(place(step * index)), 'label': _tick(step * index)}
                for index in range(round(end / step) + 1)]

    isolines = []
    for isoline in shape.isolines:
        (x1, y1), (x2, y2) = [(x(dic), y(alkalinity)) for dic, alkalinity in isoline.segment]
        label = None
        if isoline.labelled:
            angle = max(-65.0, min(65.0, math.degrees(math.atan2(y2 - y1, x2 - x1))))
            label = {'x': _fixed(x1 + LABEL_AT * (x2 - x1)), 'y': _fixed(y1 + LABEL_AT * (y2 - y1)),
                     'angle': _fixed(angle),
                     'text': f'pH {formats.number_format(Decimal(f"{isoline.ph:.1f}"), 1, use_l10n=True)}'}
        isolines.append({'ph': f'{isoline.ph:.2f}', 'labelled': isoline.labelled,
                         'colour': isoline_colour(isoline.ph), 'points': points(isoline.segment), 'label': label})
    names = _region_names(analysis)
    regions = [{'key': key, 'name': names[key], 'points': points(polygon)}
               for key in ('co2', 'h2s', 'nh3', 'safe') if (polygon := shape.regions.get(key))]
    boundaries = [{'key': key, 'name': names[key], 'points': points(line)}
                  for key in ('co2', 'h2s', 'nh3') for line in shape.boundaries.get(key, [])]
    omega_names = {'calcite': _('Ω calcite = 1'), 'aragonite': _('Ω aragonite = 1')}
    omega = [{'key': key, 'name': omega_names[key], 'points': points(line)}
             for key in ('calcite', 'aragonite') for line in shape.omega.get(key, [])]
    legend = [{'key': region['key'], 'name': region['name']} for region in regions]
    legend += [{'key': key, 'name': omega_names[key]} for key in ('calcite', 'aragonite') if shape.omega.get(key)]
    px, py = x(shape.point[0]), y(shape.point[1])
    target = path = None
    if shape.target is not None:
        tx, ty = x(shape.target[0]), y(shape.target[1])
        arm = 7
        target = {'x': _fixed(tx), 'y': _fixed(ty),
                  'lines': [[_fixed(tx - arm), _fixed(ty - arm), _fixed(tx + arm), _fixed(ty + arm)],
                            [_fixed(tx + arm), _fixed(ty - arm), _fixed(tx - arm), _fixed(ty + arm)]]}
        path = points([shape.point, shape.target])
    reagent_lines = []
    for reagent, lines in shape.reagent_lines:
        for line in lines:
            (x1, y1), (x2, y2) = [(x(dic), y(alkalinity)) for dic, alkalinity in line[-2:]]
            reagent_lines.append({'key': reagent.key, 'formula': reagent.formula, 'points': points(line),
                                  'arrow': _arrow(x1, y1, x2, y2)})
    simulator_drawing = None
    if shape.simulator:
        pixels = [(x(dic), y(alkalinity)) for dic, alkalinity in shape.simulator]
        simulator_drawing = {
            'points': ' '.join(f'{_fixed(across)},{_fixed(up)}' for across, up in pixels),
            'arrows': [_arrow(*pixels[index - 1], *pixels[index]) for index in range(1, len(pixels))
                       if math.dist(pixels[index - 1], pixels[index]) > 1],
            'end': {'x': _fixed(pixels[-1][0]), 'y': _fixed(pixels[-1][1])}}
    waypoint = None
    if shape.waypoint is not None and box.inside(shape.waypoint):
        waypoint = {'x': _fixed(x(shape.waypoint[0])), 'y': _fixed(y(shape.waypoint[1]))}
    return Chart(
        width=WIDTH, height=HEIGHT,
        plot={'left': LEFT, 'top': TOP, 'right': LEFT + PLOT, 'bottom': TOP + PLOT, 'size': PLOT,
              'centre_x': LEFT + PLOT // 2, 'centre_y': TOP + PLOT // 2, 'x_tick_y': TOP + PLOT + 18,
              'y_tick_x': LEFT - 8, 'x_title_y': HEIGHT - 10, 'y_title_x': 16},
        x_ticks=ticks(box.dic, box.dic_step, x), y_ticks=ticks(box.alkalinity, box.alkalinity_step, y),
        isolines=isolines, regions=regions, boundaries=boundaries, omega=omega, legend=legend,
        point={'x': _fixed(px), 'y': _fixed(py), 'star': _star(px, py)}, target=target, path=path,
        notes=shape.notes, box=box, reagent_lines=reagent_lines,
        wedge=points(shape.wedge) if shape.wedge else None,
        dosing_path=[points(line) for line in shape.dosing_path], waypoint=waypoint, simulator=simulator_drawing)


def _arrow(x1, y1, x2, y2, size=9):
    """An arrowhead at (x2, y2) pointing away from (x1, y1), in pixels (the source's, 0.8 π either side)."""
    angle = math.atan2(y2 - y1, x2 - x1)
    corners = [(x2, y2)] + [(x2 + size * math.cos(angle + turn), y2 + size * math.sin(angle + turn))
                            for turn in (math.pi * 0.8, -math.pi * 0.8)]
    return ' '.join(f'{_fixed(a)},{_fixed(b)}' for a, b in corners)


def _tick(value):
    return f'{value:g}'


def _star(cx, cy, radius=8):
    """A five-pointed star around a point (the source's current-point marker)."""
    corners = []
    for index in range(5):
        for angle, reach in ((index * 72 - 90, radius), (index * 72 + 36 - 90, radius * 0.4)):
            corners.append(f'{_fixed(cx + reach * math.cos(math.radians(angle)))},'
                           f'{_fixed(cy + reach * math.sin(math.radians(angle)))}')
    return ' '.join(corners)


def shown(value, decimals):
    """A number as the language writes it, at most `decimals` decimals, no trailing zeros: 8,42; 15."""
    rounded = Decimal(repr(float(value))).quantize(Decimal(1).scaleb(-decimals))
    rounded = rounded.to_integral() if rounded == rounded.to_integral() else rounded.normalize()
    return formats.number_format(rounded, use_l10n=True)


def _ph(value):
    """A pH border at two decimals, as the language writes it: 8.40, 8,40."""
    return formats.number_format(Decimal(f'{value:.2f}'), 2, use_l10n=True)


def _region_names(analysis):
    """The regions' names with their borders, as the source labels them: NH₃ toxic (pH > 8.42)."""
    names = {'safe': str(_('Safe zone') if h2s_assessed(analysis) else _('Safe zone (H₂S not assessed)'))}
    if analysis.nh3.everywhere:
        names['nh3'] = str(_('NH₃ toxic (at every pH of the chart)'))
    elif analysis.nh3.ph is not None:
        names['nh3'] = str(_('NH₃ toxic (pH > %(ph)s)') % {'ph': _ph(analysis.nh3.ph)})
    if analysis.limits.co2_mg_l is not None:
        names['co2'] = str(_('CO₂ toxic (> %(limit)s mg/L)') % {'limit': shown(analysis.limits.co2_mg_l, 1)})
    if analysis.h2s.everywhere:
        names['h2s'] = str(_('H₂S toxic (at every pH of the chart)'))
    elif analysis.h2s.ph is not None:
        names['h2s'] = str(_('H₂S toxic (pH < %(ph)s)') % {'ph': _ph(analysis.h2s.ph)})
    return names
