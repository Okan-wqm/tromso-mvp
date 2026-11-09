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
from dataclasses import asdict, dataclass, field
from decimal import Decimal

from django.utils import formats
from django.utils.translation import gettext_lazy as _

from . import chemistry, messages, native
from .evaluate import Status

PH_RANGE = native.PH_RANGE                                   # the chart's pH domain (the source's), 4 to 12.5
AXIS = native.AXIS            # the axes' ends at least: 6 mmol/L DIC and 6 meq/L alkalinity
ALERT_PH = native.ALERT_PH    # a pH border nearer than this (0.2) is a warning

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
    sulfide is as S; the conductivity is compensated to 25 °C. With the alkalinity (and the salinity) the conductivity
    and the hardness give the water's ionic strength (formula 3, chemistry.water_equilibria); `formula` is the version it
    is worked out by, the application's unless a recorder asks for another (golden v1: 1)."""
    temperature_c: float
    salinity_ppt: float
    ph: float
    alkalinity_mg_l: float
    tan_mg_l: float | None = None
    total_sulfide_ug_l: float | None = None
    calcium_mg_l: float | None = None
    oxygen_mg_l: float | None = None
    conductivity_25_us_cm: float | None = None
    hardness_mg_l: float | None = None
    formula: int = chemistry.FORMULA_VERSION


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
    reached. `margin` is how far the water's pH is from it on the safe side (negative: past it). Where it lies
    against the chart's pH range (4 to 12.5), as the core judged it: `on_chart` (shown as a number), `everywhere`
    (passed at every pH of the range), `off_chart` (not reached in the range)."""
    ph: float | None
    toxic_above: bool
    margin: float | None
    status: str
    on_chart: bool = False
    everywhere: bool = False
    off_chart: bool = False


def _border(found):
    return Border(found['ph'], found['toxic_above'], found['margin'], Status(found['status']), found['on_chart'],
                  found['everywhere'], found['off_chart'])


def judge(ph, border, toxic_above, missing=None):
    """The border and the status (the core's rule: critical past it, a warning within ALERT_PH of it, ok short of it or
    when it cannot be reached). `missing`: the status when there is nothing to judge (no value or no limit)."""
    return _border(native.judge(ph, border, toxic_above, None if missing is None else Status(missing).value))


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

    nh3_share_pct: float                     # NH₃ as a share of TAN at the water's pH, %
    h2s_share_pct: float                     # H₂S as a share of the total sulfide at the water's pH, %
    # NH₃ and CO₂ are judged on the larger of the basis their limits were set on (formula 1: the ideal water in fresh
    # water) and the activity-corrected value (cross review F1): co2_mg_l and nh3_n_mg_l above, their borders, the
    # safe TAN and the shares are the judged ones; the corrected ones are information, said beside them.
    co2_corrected_mg_l: float
    co2_basis: str                          # 'limits' or 'corrected'
    nh3_corrected_n_mg_l: float | None
    nh3_basis: str

    @property
    def provenance(self):
        """What every value of the analysis was worked out by, in words: the formula version and the ionic strength."""
        return messages.provenance(self.equilibria)

    @property
    def nh3_judged(self):
        """Which value judged the NH₃ and the corrected one beside it, in words ('' without a TAN)."""
        return messages.judged('nh3', self.nh3_basis, self.nh3_corrected_n_mg_l, self.equilibria)

    @property
    def co2_judged(self):
        """Which value judged the CO₂ and the corrected one beside it, in words."""
        return messages.judged('co2', self.co2_basis, self.co2_corrected_mg_l, self.equilibria)


def analyse(water, limits=Limits(), target=None, pressure=1.0):
    """The values of a water against the limits (the core's analysis, chemcore/core/src/analysis.rs): DIC and CO₂ from
    the alkalinity and the pH, NH₃-N from the TAN, H₂S from the total sulfide, each limit as a pH border, the oxygen
    saturation at `pressure` (atm)."""
    found = native.analyse(
        **asdict(water), **asdict(limits), target_ph=None if target is None else target.ph,
        target_alkalinity_mg_l=None if target is None else target.alkalinity_mg_l, pressure=pressure)
    for key in ('co2', 'nh3', 'h2s'):
        found[key] = _border(found[key])
    return Analysis(water=water, limits=limits, target=target, **found)


def alkalinity_floor(temperature_c, salinity_ppt, ph, **medium):
    """The alkalinity (mg/L as CaCO₃) a water of this pH has at least: hydroxide and borate are alkalinity too, so at a
    high pH the alkalinity has a floor, below which the DIC would be negative. `medium`: the water's alkalinity_mg_l,
    conductivity_25_us_cm, hardness_mg_l and formula (formula 3's constants depend on its ions)."""
    return native.alkalinity_floor(temperature_c, salinity_ppt, ph, **medium)


def why_impossible(temperature_c, salinity_ppt, ph, alkalinity_mg_l, **ions):
    """Why a water of this pH and alkalinity cannot be (its alkalinity at or below the floor of `alkalinity_floor`),
    in the active language; '' when it can. The calculator's form and a unit's chart ask here. `ions`: its
    conductivity_25_us_cm and hardness_mg_l, and the formula."""
    floor = native.why_impossible(temperature_c, salinity_ppt, ph, alkalinity_mg_l, **ions)
    if floor is None:
        return ''
    return str(_('At this pH the alkalinity is above %(floor)s mg/L as CaCO₃: the hydroxide and borate alone are '
                 'that much.') % {'floor': shown(floor, 1)})


def possible(temperature_c, salinity_ppt, ph, alkalinity_mg_l, **ions):
    """Whether a water of this pH and alkalinity can be (`why_impossible` has nothing to say)."""
    return not why_impossible(temperature_c, salinity_ppt, ph, alkalinity_mg_l, **ions)


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


def box_of(analysis, extra=()):
    """The box that holds the water, the target, the alkalinity band and the `extra` points (DIC, alkalinity) with
    10 % to spare (the core's 1-2-5 steps; native.ChartTooLargeError beyond 12 steps of 5e7)."""
    target = None if analysis.target_dic is None else (analysis.target_dic, analysis.target_alkalinity_meq)
    return Box(*native.box_of(analysis.dic, analysis.alkalinity_meq, target, analysis.limits.alkalinity_high_mg_l,
                              [tuple(point) for point in extra]))


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


def _inputs(analysis):
    """What the core needs of an analysis: its water and limits as dicts, its target as (pH, alkalinity), its pressure."""
    target = analysis.target
    return (asdict(analysis.water), asdict(analysis.limits),
            None if target is None else (target.ph, target.alkalinity_mg_l), analysis.pressure_atm)


def safe_zone_gaps(analysis):
    """Why there can be no safe zone, as notes (the core's codes, said by farm/water/messages.py): a missing value is
    never taken for a safe one. Every limit the zone is bounded by must be judged: the TAN and its NH₃ limit, the CO₂
    limit, the alkalinity band, and an H₂S limit when a total sulfide is given. A water without a total sulfide is not
    a gap: its zone is drawn, named "H₂S not assessed"."""
    water, limits, target, pressure = _inputs(analysis)
    return [messages.note(code) for code in native.safe_zone_gaps(water, limits, target, pressure)]


def h2s_assessed(analysis):
    """Whether the safe zone takes H₂S into account: a total sulfide was given."""
    return analysis.h2s.status != Status.NOT_MEASURED


def safe_zone(analysis, box):
    """The safe region in a box (the core's): the alkalinity band, from the NH₃ isoline (the highest pH allowed; the
    chart's top pH when the TAN cannot reach its limit) to the CO₂ curve or the H₂S isoline, whichever is the higher pH.
    [] when a value or a limit it needs is missing (safe_zone_gaps), or when the band has no safe pH."""
    water, limits, target, pressure = _inputs(analysis)
    return native.safe_zone(water, limits, (box.dic, box.alkalinity, box.dic_step, box.alkalinity_step), target, pressure)


def geometry(analysis, layers=ALL_LAYERS, dosing=None, simulator=(), extent=()):
    """The chart of an analysis, the layers asked for, in the chart's units (the core's,
    chemcore/core/src/geometry.rs); a note says why a layer asked for is not drawn. `dosing`: the dosing layer (a
    dosing.Visual); `simulator`: the water after each step of the simulator, (DIC, alkalinity), the water first;
    `extent`: more points (DIC, alkalinity) the box must hold, drawn as nothing (a replay's frames, A6)."""
    water, limits, target, pressure = _inputs(analysis)
    drawn = None if dosing is None else {
        'lines': [(reagent.key, line) for reagent, line in dosing.lines], 'wedge': list(dosing.wedge or []),
        'path': list(dosing.path or []), 'waypoint': dosing.waypoint}
    found = native.geometry(water, limits, target, pressure, sorted(layers), drawn,
                            [tuple(point) for point in simulator], [tuple(point) for point in extent])
    reagents = {} if dosing is None else {reagent.key: reagent for reagent, _line in dosing.lines}
    shape = Geometry(
        Box(*found['box']), isolines=[Isoline(ph, labelled, segment) for ph, labelled, segment in found['isolines']],
        regions=found['regions'], boundaries=found['boundaries'], omega=found['omega'], point=found['point'],
        target=found['target'], reagent_lines=[(reagents[key], lines) for key, lines in found['reagent_lines']],
        wedge=found['wedge'], dosing_path=found['dosing_path'], waypoint=found['waypoint'],
        simulator=found['simulator'], notes=[messages.note(code) for code in found['notes']])
    if dosing is not None and 'dosing' in layers and dosing.note:
        shape.notes.append(dosing.note)
    return shape


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


def _flat(polyline):
    return [float(value) for point in polyline for value in point]


def _pairs(values):
    return [(values[index], values[index + 1]) for index in range(0, len(values), 2)]


def figure(analysis, shape):
    """A chart's whole geometry (`geometry`) as numbers and words a JSON document holds: THE shape the server's SVG
    (`render`) and the replay's player draw from (A8). Every line a flat array [DIC, alkalinity, DIC, alkalinity, ...]
    in the chart's units; the regions and borders with their names and the notes in the active language."""
    box = shape.box
    names = _region_names(analysis)
    return {
        'box': [float(box.dic), float(box.alkalinity), float(box.dic_step), float(box.alkalinity_step)],
        'isolines': [[float(isoline.ph), int(isoline.labelled), *_flat(isoline.segment)] for isoline in shape.isolines],
        'regions': [[key, names[key], _flat(polygon)]
                    for key in ('co2', 'h2s', 'nh3', 'safe') if (polygon := shape.regions.get(key))],
        'boundaries': [[key, names[key], _flat(line)] for key in ('co2', 'h2s', 'nh3')
                       for line in shape.boundaries.get(key, [])],
        'omega': [[key, _flat(line)] for key in ('calcite', 'aragonite') for line in shape.omega.get(key, [])],
        'point': [float(shape.point[0]), float(shape.point[1])],
        'target': None if shape.target is None else [float(shape.target[0]), float(shape.target[1])],
        'reagent_lines': [[reagent.key, reagent.formula, _flat(line)]
                          for reagent, lines in shape.reagent_lines for line in lines],
        'wedge': _flat(shape.wedge),
        'dosing_path': [_flat(line) for line in shape.dosing_path],
        'waypoint': None if shape.waypoint is None else [float(shape.waypoint[0]), float(shape.waypoint[1])],
        'simulator': _flat(shape.simulator),
        'notes': [str(note) for note in shape.notes],
    }


def draw(analysis, layers=ALL_LAYERS, dosing=None, simulator=(), extent=()):
    """The chart of an analysis as the template draws it (`dosing`, `simulator` and `extent` as `geometry` takes them):
    the SVG's parts drawn from its figure."""
    return render(figure(analysis, geometry(analysis, layers, dosing, simulator, extent)))


def render(figure):
    """The SVG's parts (Chart) of a figure, from the figure alone: the server draws every chart through here, and the
    replay's player draws the same figures."""
    box = Box(*figure['box'])

    def x(dic):
        return LEFT + dic / box.dic * PLOT

    def y(alkalinity):
        return TOP + PLOT - alkalinity / box.alkalinity * PLOT

    def points(flat):
        return ' '.join(f'{_fixed(x(dic))},{_fixed(y(alkalinity))}' for dic, alkalinity in _pairs(flat))

    def ticks(end, step, place):
        return [{'at': _fixed(place(step * index)), 'label': _tick(step * index)}
                for index in range(round(end / step) + 1)]

    isolines = []
    for ph, labelled, *segment in figure['isolines']:
        (x1, y1), (x2, y2) = [(x(dic), y(alkalinity)) for dic, alkalinity in _pairs(segment)]
        label = None
        if labelled:
            angle = max(-65.0, min(65.0, math.degrees(math.atan2(y2 - y1, x2 - x1))))
            label = {'x': _fixed(x1 + LABEL_AT * (x2 - x1)), 'y': _fixed(y1 + LABEL_AT * (y2 - y1)),
                     'angle': _fixed(angle),
                     'text': f'pH {formats.number_format(Decimal(f"{ph:.1f}"), 1, use_l10n=True)}'}
        isolines.append({'ph': f'{ph:.2f}', 'labelled': bool(labelled),
                         'colour': isoline_colour(ph), 'points': points(segment), 'label': label})
    regions = [{'key': key, 'name': name, 'points': points(polygon)} for key, name, polygon in figure['regions']]
    boundaries = [{'key': key, 'name': name, 'points': points(line)} for key, name, line in figure['boundaries']]
    omega_names = {'calcite': _('Ω calcite = 1'), 'aragonite': _('Ω aragonite = 1')}
    omega = [{'key': key, 'name': omega_names[key], 'points': points(line)} for key, line in figure['omega']]
    legend = [{'key': region['key'], 'name': region['name']} for region in regions]
    legend += [{'key': key, 'name': omega_names[key]} for key in ('calcite', 'aragonite')
               if any(each == key for each, _line in figure['omega'])]
    px, py = x(figure['point'][0]), y(figure['point'][1])
    target = path = None
    if figure['target'] is not None:
        tx, ty = x(figure['target'][0]), y(figure['target'][1])
        arm = 7
        target = {'x': _fixed(tx), 'y': _fixed(ty),
                  'lines': [[_fixed(tx - arm), _fixed(ty - arm), _fixed(tx + arm), _fixed(ty + arm)],
                            [_fixed(tx + arm), _fixed(ty - arm), _fixed(tx - arm), _fixed(ty + arm)]]}
        path = points([*figure['point'], *figure['target']])
    reagent_lines = []
    for key, formula, line in figure['reagent_lines']:
        (x1, y1), (x2, y2) = [(x(dic), y(alkalinity)) for dic, alkalinity in _pairs(line)[-2:]]
        reagent_lines.append({'key': key, 'formula': formula, 'points': points(line), 'arrow': _arrow(x1, y1, x2, y2)})
    simulator_drawing = None
    if figure['simulator']:
        pixels = [(x(dic), y(alkalinity)) for dic, alkalinity in _pairs(figure['simulator'])]
        simulator_drawing = {
            'points': ' '.join(f'{_fixed(across)},{_fixed(up)}' for across, up in pixels),
            'arrows': [_arrow(*pixels[index - 1], *pixels[index]) for index in range(1, len(pixels))
                       if math.dist(pixels[index - 1], pixels[index]) > 1],
            'end': {'x': _fixed(pixels[-1][0]), 'y': _fixed(pixels[-1][1])}}
    waypoint = None
    if figure['waypoint'] is not None and box.inside(tuple(figure['waypoint'])):
        waypoint = {'x': _fixed(x(figure['waypoint'][0])), 'y': _fixed(y(figure['waypoint'][1]))}
    return Chart(
        width=WIDTH, height=HEIGHT,
        plot={'left': LEFT, 'top': TOP, 'right': LEFT + PLOT, 'bottom': TOP + PLOT, 'size': PLOT,
              'centre_x': LEFT + PLOT // 2, 'centre_y': TOP + PLOT // 2, 'x_tick_y': TOP + PLOT + 18,
              'y_tick_x': LEFT - 8, 'x_title_y': HEIGHT - 10, 'y_title_x': 16},
        x_ticks=ticks(box.dic, box.dic_step, x), y_ticks=ticks(box.alkalinity, box.alkalinity_step, y),
        isolines=isolines, regions=regions, boundaries=boundaries, omega=omega, legend=legend,
        point={'x': _fixed(px), 'y': _fixed(py), 'star': _star(px, py)}, target=target, path=path,
        notes=list(figure['notes']), box=box, reagent_lines=reagent_lines,
        wedge=points(figure['wedge']) if figure['wedge'] else None,
        dosing_path=[points(line) for line in figure['dosing_path']], waypoint=waypoint, simulator=simulator_drawing)


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
