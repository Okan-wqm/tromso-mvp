"""The four small charts beside the Water Quality Management Chart, each a value against the pH: the
un-ionised ammonia of the TAN, the shares of the total sulfide as H₂S and HS⁻, the shares of the DIC as CO₂,
HCO₃⁻ and CO₃²⁻, and the calcite and aragonite saturation index at the water's DIC. Ported from the source's
calculator (web/shared-ui/src/water-chemistry/components/SecondaryCharts.tsx: UiaVsPhChart, H2sVsPhChart,
CarbonateVsPhChart, CalciteSaturationChart; their data from libs/aquaculture-engines/src/water-chemistry/
ammonia-calc.ts generateUIAvsPHData and generateH2SvsPHData, co2-calc.ts generateCarbonateVsPHData and
generateSaturationVsPHData; their bands from web/shared-ui/src/water-chemistry/chart-zones.ts). Every value
is farm/water/chemistry.py's, the same as the big chart's and the results', and every band is the border the
results show (farm/water/deffeyes.py). Drawn on the server as SVG, as the big chart is, without a script.

What each shows, as the source draws it (the corrections are in the bug document, WQ-40 on):
- NH₃-N: TAN × K / (K + [H⁺]) from pH 6 to 9.5, the NH₃-N limit as a line, up to 2.5 times the limit; the
  axis is widened to hold the water's pH and its NH₃-N, which the source let fall off the chart.
- H₂S and HS⁻: [H⁺] / (K + [H⁺]) and its rest, in % of the total sulfide, from pH 4 to 12.5.
- CO₂, HCO₃⁻, CO₃²⁻: α0, α1, α2 in % of the DIC, from pH 4 to 12.
- Saturation index: log10(Ω), Ω = [Ca²⁺] [CO₃²⁻] / Ksp (Mucci 1983) at the water's DIC, from pH 6 to 9.5
  widened to the water's pH; only from 5 to 44 ‰ with the calcium given (WQ-32), as the big chart's lines.
- The bands of NH₃ and H₂S: past the border danger, within 0.2 pH of it alert, else safe; none when the
  value or its limit is missing (a missing value is never taken for a safe one)."""
import math
from dataclasses import dataclass, field

from django.utils.translation import gettext, gettext_lazy as _

from . import chemistry
from .deffeyes import ALERT_PH, OMEGA_SALINITY, PH_RANGE, Box, clip_polyline, shown
from .evaluate import Status

STEP = 0.05                  # pH between two points of a curve
JUDGED = {Status.OK, Status.WARNING, Status.CRITICAL}


@dataclass
class Plot:
    """One chart in its own units: pH across, the value up."""
    key: str
    x: tuple                                           # pH from, to
    y: tuple                                           # value from, to
    unit: str                                          # 'mg_l', 'percent' or 'index': how the axis reads
    series: list = field(default_factory=list)         # [(key, name, [(pH, value)])]
    bands: list = field(default_factory=list)          # [(kind, pH from, pH to)]: 'safe', 'alert', 'danger'
    verticals: list = field(default_factory=list)      # [(key, pH, label)]
    horizontals: list = field(default_factory=list)    # [(key, value, label)]
    dots: list = field(default_factory=list)           # [(key, pH, value, name)]


def widen(span, ph, margin=0.25):
    """A pH axis that holds the water's pH, its ends on half units."""
    low, high = span
    return (max(PH_RANGE[0], min(low, math.floor((ph - margin) * 2) / 2)),
            max(high, math.ceil((ph + margin) * 2) / 2))


def grid(span):
    low, high = span
    count = round((high - low) / STEP)
    return [low + (high - low) * index / count for index in range(count + 1)]


def bands(border, low, high):
    """The danger, alert and safe bands of a border on a pH axis (the source's getVisibleNH3ChartZones and
    getVisibleH2SChartZones): toxic above (NH₃) or below (H₂S) the border, alert within ALERT_PH of it on the
    safe side, each cut to the axis, so a border a little beyond the axis still shows its alert strip (the
    source drew it all safe, though a water there is a warning); [] when the limit is not judged (no value or
    no limit)."""
    if border.status not in JUDGED:
        return []
    if border.ph is None:                              # the limit cannot be reached at any pH
        return [('safe', low, high)]
    edge = border.ph
    if border.toxic_above:
        found = [('safe', low, edge - ALERT_PH), ('alert', edge - ALERT_PH, edge), ('danger', edge, high)]
    else:
        found = [('danger', low, edge), ('alert', edge, edge + ALERT_PH), ('safe', edge + ALERT_PH, high)]
    cut = [(kind, max(start, low), min(end, high)) for kind, start, end in found]
    return [band for band in cut if band[2] > band[1]]


def _ph_label(ph):
    return f'pH {shown(ph, 2)}'


def _verticals(analysis, border, span):
    lines = [('water', analysis.water.ph, _ph_label(analysis.water.ph))]
    if border.ph is not None and span[0] <= border.ph <= span[1]:
        lines.append(('border', border.ph, str(_('Border %(ph)s') % {'ph': shown(border.ph, 2)})))
    return lines


# ---- the four charts ------------------------------------------------------------------------------------
def nh3_plot(analysis):
    """NH₃-N against pH; None without the TAN."""
    tan, limit, eq = analysis.water.tan_mg_l, analysis.limits.nh3_n_mg_l, analysis.equilibria
    if tan is None:
        return None
    span = widen((6.0, 9.5), analysis.water.ph)
    curve = [(ph, tan * eq.nh3_share(ph)) for ph in grid(span)]
    top = 2.5 * limit if limit else max(value for _ph, value in curve)
    top = max(top, 1.15 * analysis.nh3_n_mg_l) or 1.0
    plot = Plot('nh3', span, (0.0, top), 'mg_l', series=[('nh3', _('NH₃-N'), curve)],
                bands=bands(analysis.nh3, *span), verticals=_verticals(analysis, analysis.nh3, span))
    plot.dots.append(('water', analysis.water.ph, analysis.nh3_n_mg_l, _('The water')))
    if limit:
        plot.horizontals.append(('limit', limit, _('Limit')))
        if analysis.nh3.ph is not None and span[0] <= analysis.nh3.ph <= span[1]:
            plot.dots.append(('border', analysis.nh3.ph, limit, _('The border')))
    return plot


def h2s_plot(analysis):
    """The shares of the total sulfide as H₂S and HS⁻ against pH, in %."""
    eq = analysis.equilibria
    span = (PH_RANGE[0], PH_RANGE[1])
    shares = [(ph, 100 * eq.h2s_share(ph)) for ph in grid(span)]
    plot = Plot('h2s', span, (0.0, 100.0), 'percent',
                series=[('h2s', _('H₂S'), shares), ('hs', _('HS⁻'), [(ph, 100 - share) for ph, share in shares])],
                bands=bands(analysis.h2s, *span), verticals=_verticals(analysis, analysis.h2s, span))
    plot.dots.append(('water', analysis.water.ph, 100 * eq.h2s_share(analysis.water.ph), _('The water')))
    return plot


def carbonate_plot(analysis):
    """The shares of the DIC as CO₂, HCO₃⁻ and CO₃²⁻ against pH, in %."""
    eq = analysis.equilibria
    span = (PH_RANGE[0], 12.0)
    points = [(ph, eq.fractions(ph)) for ph in grid(span)]
    names = (('co2', _('CO₂')), ('hco3', _('HCO₃⁻')), ('co3', _('CO₃²⁻')))
    series = [(key, name, [(ph, 100 * shares[index]) for ph, shares in points])
              for index, (key, name) in enumerate(names)]
    return Plot('carbonate', span, (0.0, 100.0), 'percent', series=series,
                verticals=[('water', analysis.water.ph, _ph_label(analysis.water.ph))])


def saturation_index(eq, dic, ph, calcium_mg_l, ksp):
    """log10 Ω of a water: Ω = [Ca²⁺] [CO₃²⁻] / Ksp, concentrations per litre (WQ-32)."""
    product = calcium_mg_l / chemistry.MG_CALCIUM_PER_MOL * eq.carbonate(dic, ph) / 1000
    return math.log10(product / ksp)


def saturation_plot(analysis):
    """The calcite and aragonite saturation index against pH at the water's DIC; None without the calcium or
    outside Mucci's salinities."""
    water, eq = analysis.water, analysis.equilibria
    if not water.calcium_mg_l or not OMEGA_SALINITY[0] <= water.salinity_ppt <= OMEGA_SALINITY[1]:
        return None
    span = widen((6.0, 9.5), water.ph)
    series = [(key, name, [(ph, saturation_index(eq, analysis.dic, ph, water.calcium_mg_l, ksp)) for ph in grid(span)])
              for key, name, ksp in (('calcite', _('Calcite'), eq.ksp_calcite),
                                     ('aragonite', _('Aragonite'), eq.ksp_aragonite))]
    values = [value for _key, _name, curve in series for _ph, value in curve]
    low, high = math.floor(min(min(values), 0) * 2) / 2, math.ceil(max(max(values), 0) * 2) / 2
    if high - low < 1:
        high = low + 1
    return Plot('saturation', span, (low, high), 'index', series=series,
                verticals=[('water', water.ph, _ph_label(water.ph))],
                horizontals=[('zero', 0.0, _('Ω = 1'))])


def plots(analysis):
    """The four charts by key; a chart that cannot be drawn is None (the template says why)."""
    return {'nh3': nh3_plot(analysis), 'h2s': h2s_plot(analysis), 'carbonate': carbonate_plot(analysis),
            'saturation': saturation_plot(analysis)}


# ---- the SVG --------------------------------------------------------------------------------------------
WIDTH, HEIGHT = 400, 260
LEFT, TOP, PLOT_WIDTH, PLOT_HEIGHT = 58, 14, 326, 196


def _fixed(value):
    return f'{value:.2f}'


def nice_step(span, count=4):
    """A 1-2-2.5-5 step that cuts `span` into about `count` parts."""
    raw = span / count
    power = 10 ** math.floor(math.log10(raw))
    return next(base * power for base in (1, 2, 2.5, 5, 10) if base * power >= raw * (1 - 1e-9))


def _decimals(step):
    """The decimals a tick of this step needs: 0.0025 → 4, 0.5 → 1, 25 → 0."""
    decimals = 0
    while abs(step * 10 ** decimals - round(step * 10 ** decimals)) > 1e-9 and decimals < 8:
        decimals += 1
    return decimals


@dataclass
class Drawing:
    """A plot's SVG parts in pixels, every coordinate a string with a dot decimal whatever the language."""
    key: str
    width: int
    height: int
    frame: dict
    x_ticks: list
    y_ticks: list
    bands: list
    series: list
    verticals: list
    horizontals: list
    dots: list


def draw(plot):
    if plot is None:
        return None
    (x_low, x_high), (y_low, y_high) = plot.x, plot.y
    y_step = 25.0 if plot.unit == 'percent' else nice_step(y_high - y_low)
    if plot.unit != 'percent':                         # the ends on whole steps, so every tick is one
        y_low = math.floor(y_low / y_step + 1e-9) * y_step
        y_high = y_low + math.ceil((y_high - y_low) / y_step - 1e-9) * y_step
    box = Box(x_high - x_low, y_high - y_low, 1, 1)

    def x(ph):
        return LEFT + (ph - x_low) / (x_high - x_low) * PLOT_WIDTH

    def y(value):
        return TOP + PLOT_HEIGHT - (value - y_low) / (y_high - y_low) * PLOT_HEIGHT

    def inside(ph, value):
        return x_low - 1e-9 <= ph <= x_high + 1e-9 and y_low - 1e-9 <= value <= y_high + 1e-9

    x_step = 0.5 if x_high - x_low <= 4 else 1.0
    x_ticks = [{'at': _fixed(x(x_low + x_step * index)), 'label': shown(x_low + x_step * index, 1)}
               for index in range(round((x_high - x_low) / x_step) + 1)]
    decimals = _decimals(y_step)
    y_ticks = []
    for index in range(round((y_high - y_low) / y_step) + 1):
        value = y_low + y_step * index
        label = shown(value, decimals)
        # Translators: a percentage; write the sign where your language puts it (Turkish: %%%(value)s).
        y_ticks.append({'at': _fixed(y(value)),
                        'label': gettext('%(value)s %%') % {'value': label} if plot.unit == 'percent' else label})
    series = []
    for key, name, curve in plot.series:
        shifted = [(ph - x_low, value - y_low) for ph, value in curve]
        for line in clip_polyline(shifted, box):
            series.append({'key': key, 'name': str(name),
                           'points': ' '.join(f'{_fixed(x(a + x_low))},{_fixed(y(b + y_low))}' for a, b in line)})
    return Drawing(
        key=plot.key, width=WIDTH, height=HEIGHT,
        frame={'left': LEFT, 'top': TOP, 'width': PLOT_WIDTH, 'height': PLOT_HEIGHT, 'right': LEFT + PLOT_WIDTH,
               'bottom': TOP + PLOT_HEIGHT, 'centre_x': LEFT + PLOT_WIDTH // 2, 'x_tick_y': TOP + PLOT_HEIGHT + 16,
               'y_tick_x': LEFT - 6, 'x_title_y': HEIGHT - 6},
        x_ticks=x_ticks, y_ticks=y_ticks,
        bands=[{'kind': kind, 'x': _fixed(x(low)), 'width': _fixed(x(high) - x(low))}
               for kind, low, high in plot.bands],
        series=series,
        verticals=[{'key': key, 'x': _fixed(x(ph)), 'label': str(label), 'label_y': TOP + 10 + 13 * index,
                    'anchor': 'end' if x(ph) > LEFT + PLOT_WIDTH * 0.75 else 'start'}
                   for index, (key, ph, label) in enumerate(plot.verticals) if x_low <= ph <= x_high],
        horizontals=[{'key': key, 'y': _fixed(y(value)), 'label': str(label)} for key, value, label in plot.horizontals
                     if y_low <= value <= y_high],
        dots=[{'key': key, 'x': _fixed(x(ph)), 'y': _fixed(y(value)), 'name': str(name)}
              for key, ph, value, name in plot.dots if value is not None and inside(ph, value)])
