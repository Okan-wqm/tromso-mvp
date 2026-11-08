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

from . import native
from .deffeyes import Box, _inputs, shown
from .evaluate import Status



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


SERIES = {'nh3': _('NH₃-N'), 'h2s': _('H₂S'), 'hs': _('HS⁻'), 'co2': _('CO₂'), 'hco3': _('HCO₃⁻'),
          'co3': _('CO₃²⁻'), 'calcite': _('Calcite'), 'aragonite': _('Aragonite')}
HORIZONTALS = {'limit': _('Limit'), 'zero': _('Ω = 1')}
DOTS = {'water': _('The water'), 'border': _('The border')}


def bands(border, low, high):
    """The danger, alert and safe bands of a border on a pH axis (the core's, after the source's
    getVisibleNH3ChartZones and getVisibleH2SChartZones): toxic above (NH₃) or below (H₂S) the border, alert within
    ALERT_PH of it on the safe side, each cut to the axis, so a border a little beyond the axis still shows its alert
    strip; [] when the limit is not judged (no value or no limit)."""
    return native.bands(border.ph, border.toxic_above, Status(border.status).value, low, high)


def _ph_label(ph):
    return f'pH {shown(ph, 2)}'


def _vertical(key, ph):
    if key == 'water':
        return key, ph, _ph_label(ph)
    return key, ph, str(_('Border %(ph)s') % {'ph': shown(ph, 2)})


def _plot(key, found):
    """A chart of the core's numbers with its words."""
    if found is None:
        return None
    return Plot(key, found['x'], found['y'], found['unit'],
                series=[(series, SERIES[series], curve) for series, curve in found['series']],
                bands=found['bands'], verticals=[_vertical(*vertical) for vertical in found['verticals']],
                horizontals=[(name, value, HORIZONTALS[name]) for name, value in found['horizontals']],
                dots=[(name, ph, value, DOTS[name]) for name, ph, value in found['dots']])


def plots(analysis):
    """The four charts by key (the core's, chemcore/core/src/plots.rs); a chart that cannot be drawn is None (the
    template says why)."""
    water, limits, target, pressure = _inputs(analysis)
    return {key: _plot(key, found) for key, found in native.plots(water, limits, target, pressure).items()}


def saturation_index(eq, dic, ph, calcium_mg_l, ksp):
    """log10 Ω of a water: Ω = [Ca²⁺] [CO₃²⁻] / Ksp, concentrations per litre (WQ-32; the core's)."""
    return native.saturation_index(eq.temp_c, eq.salinity, dic, ph, calcium_mg_l, ksp)


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
        for line in native.clip_polyline(shifted, (box.dic, box.alkalinity, box.dic_step, box.alkalinity_step)):
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
