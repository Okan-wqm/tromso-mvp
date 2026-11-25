"""A sensor chart as server-rendered SVG (no chart library, as the Deffeyes chart): the mean of each bucket as a line,
its lowest and highest as a band, the gaps shaded (a gap is never bridged: the line breaks there), the manual and lab
samples as points, the moments a sensor was moved or calibrated as marks, and a header that names what the buckets are
(stored values, minute or hourly summaries, the site's days). Every word is a translated string; every value the person
typed (a unit's code) is escaped."""
from django.utils import formats, timezone
from django.utils.html import escape
from django.utils.translation import gettext as _

from farm.water import messages

from . import read

WIDTH, HEIGHT = 720, 260
LEFT, RIGHT, TOP, BOTTOM = 56, 16, 30, 34


def tier_text(tier):
    return {read.RAW: _('stored values'), read.ROLLUP_1H: _('hourly summaries'),
            read.LOCAL_DAY: _('days on the site’s clock')}[tier]


def width_text(width):
    seconds = int(width.total_seconds())
    if seconds < 60:
        return _('%(count)d s') % {'count': seconds}
    if seconds < 3600:
        return _('%(count)d min') % {'count': seconds // 60}
    if seconds < 86400:
        return _('%(count)d h') % {'count': seconds // 3600}
    return _('%(count)d d') % {'count': seconds // 86400}


def _number(value):
    return f'{value:.2f}'


def head_text(chart, title):
    """What the chart is: the place, the quantity, what its buckets are and how wide."""
    return _('%(title)s · %(quantity)s · %(tier)s, %(width)s each') % {
        'title': title, 'quantity': chart.quantity.label, 'tier': tier_text(chart.tier), 'width': width_text(chart.width)}


def marker_text(marker):
    return {'move': _('Sensor moved here'), 'ph_scale': _('pH scale changed: the values before are not used')
            }.get(marker.kind, _('Calibrated'))


def draw(chart, title):
    """The chart's SVG (a string, safe to put in a page as it is)."""
    head = head_text(chart, title)
    parts = [f'<svg class="sensor-chart" viewBox="0 0 {WIDTH} {HEIGHT}" role="img" data-tier="{chart.tier}" '
             f'xmlns="http://www.w3.org/2000/svg"><title>{escape(head)}</title>',
             f'<text class="chart-head" x="{LEFT}" y="18">{escape(head)}</text>']
    if chart.empty and not chart.samples:
        parts.append(f'<text class="chart-empty" x="{WIDTH / 2}" y="{HEIGHT / 2}" text-anchor="middle">'
                     f'{escape(_("No sensor values in this time."))}</text></svg>')
        return ''.join(parts)
    values = [b.vmin for b in chart.buckets] + [b.vmax for b in chart.buckets] + [float(v) for _a, v, _s in chart.samples]
    low, high = min(values), max(values)
    pad = (high - low) * 0.08 or max(abs(high) * 0.05, 0.5)
    low, high = low - pad, high + pad
    span = (chart.end - chart.start).total_seconds()

    def x(moment):
        share = (moment - chart.start).total_seconds() / span
        return LEFT + max(0.0, min(1.0, share)) * (WIDTH - LEFT - RIGHT)

    def y(value):
        return TOP + (high - value) / (high - low) * (HEIGHT - TOP - BOTTOM)

    for start, end in chart.gaps:
        parts.append(f'<rect class="chart-gap" x="{_number(x(start))}" y="{TOP}" width="{_number(max(x(end) - x(start), 1))}" '
                     f'height="{HEIGHT - TOP - BOTTOM}"><title>{escape(_("No value"))}</title></rect>')
    gap_starts = {start for start, _end in chart.gaps}
    runs, run = [], []
    for bucket in chart.buckets:
        run.append(bucket)
        if bucket.last_ts in gap_starts:
            runs.append(run)
            run = []
    if run:
        runs.append(run)
    for run in runs:
        middle = [(x(b.start + (b.end - b.start) / 2), b) for b in run]
        band = [f'{_number(px)},{_number(y(b.vmax))}' for px, b in middle] + [
            f'{_number(px)},{_number(y(b.vmin))}' for px, b in reversed(middle)]
        parts.append(f'<polygon class="chart-band" points="{" ".join(band)}"/>')
        line = ' '.join(f'{_number(px)},{_number(y(b.avg))}' for px, b in middle)
        parts.append(f'<polyline class="chart-line" points="{line}"/>')
        for px, b in middle:
            if b.role == 'backup' or b.origin == read.SYSTEM_SENSOR:
                parts.append(f'<circle class="chart-other-source" cx="{_number(px)}" cy="{_number(y(b.avg))}" r="2.5">'
                             f'<title>{escape(_("From the backup or the system’s channel"))}</title></circle>')
    for at, value, _source in chart.samples:
        parts.append(f'<circle class="chart-sample" cx="{_number(x(at))}" cy="{_number(y(float(value)))}" r="4">'
                     f'<title>{escape(_("Sample"))}: {escape(formats.localize(value))}</title></circle>')
    for marker in chart.markers:
        label = marker_text(marker)
        parts.append(f'<line class="chart-marker" x1="{_number(x(marker.at))}" x2="{_number(x(marker.at))}" y1="{TOP}" '
                     f'y2="{HEIGHT - BOTTOM}"><title>{escape(label)}</title></line>')
    for value in (low + pad, (low + high) / 2, high - pad):
        parts.append(f'<text class="chart-tick" x="{LEFT - 6}" y="{_number(y(value))}" text-anchor="end" '
                     f'dominant-baseline="middle">{escape(formats.localize(round(value, 2)))}</text>')
    for moment, anchor in ((chart.start, 'start'), (chart.end, 'end')):
        shown = formats.date_format(timezone.localtime(moment, chart.zone), 'DATETIME_FORMAT')
        parts.append(f'<text class="chart-tick" x="{_number(x(moment))}" y="{HEIGHT - 12}" text-anchor="{anchor}">'
                     f'{escape(shown)}</text>')
    parts.append(f'<rect class="chart-frame" x="{LEFT}" y="{TOP}" width="{WIDTH - LEFT - RIGHT}" '
                 f'height="{HEIGHT - TOP - BOTTOM}"/></svg>')
    return ''.join(parts)


def notes(chart):
    """What the person should know to read the chart right, translated."""
    found = []
    if chart.reduced:
        found.append(_('A channel that stores a value when it moves counts the values it did not store at the row that '
                       'closes their run: less than two heartbeats late.'))
    if chart.tier != read.RAW:
        found.append(_('Each point is the mean of its time; the band is its lowest and highest value.'))
    if chart.samples:
        found.append(_('The dots are manual and lab samples.'))
    scales = sorted({(segment.channel_no, segment.ph_scale) for segment in chart.segments if segment.ph_scale})
    for channel_no, scale in scales:
        # A pH channel on another scale (sensors.Channel.ph_scale): drawn as the probe measured it; the water pages put
        # it on the NBS scale with the temperature and salinity of each moment (farm/water/read.py).
        found.append(_('Channel #%(number)d is drawn as its probe measured it, on the %(scale)s, not converted: the '
                       'samples and the water pages are on the NBS scale.') % {
            'number': channel_no, 'scale': messages.PH_SCALES[scale]})
    for channel_no, changed in chart.cuts:
        # Whether the change is inside the window or after it (a window wholly before it is blank: the review of the
        # water-chemistry audit, C4), the chart says why those values are not drawn.
        found.append(_('Channel #%(number)d’s values before %(time)s are not drawn: its pH scale was changed then, and '
                       'the scale they were measured on is not known.') % {
            'number': channel_no,
            'time': formats.date_format(timezone.localtime(changed, chart.zone), 'DATETIME_FORMAT')})
    return found


def _epoch(moment):
    return int(moment.timestamp())


def _at(chart, moment):
    return formats.date_format(timezone.localtime(moment, chart.zone), 'DATETIME_FORMAT')


def _amount(chart, value):
    return f'{formats.number_format(value, chart.quantity.decimals)} {chart.quantity.unit}'.strip()


def gap_text(chart):
    """The chart's gaps in words ("from 20.11.2026 03:00 to 20.11.2026 13:00; ..."), '' without one: what a person who
    cannot see the shading reads (WCAG 1.1.1), and the caption's sentence."""
    return '; '.join(_('from %(start)s to %(end)s') % {'start': _at(chart, start), 'end': _at(chart, end)}
                     for start, end in chart.gaps)


def said(chart):
    """[[term, words]] of what the chart shows, for a screen reader and for whoever cannot see it (ChartFrame `values`):
    the latest mean with its time, the lowest and the highest with theirs, the gaps; each in the quantity's decimals and
    the site's clock. Nothing for an empty chart (its own sentence says so)."""
    found = []
    buckets = chart.buckets
    if buckets:
        last = buckets[-1]
        low = min(buckets, key=lambda bucket: bucket.vmin)
        high = max(buckets, key=lambda bucket: bucket.vmax)
        for term, value, moment in ((_('Latest'), last.avg, last.last_ts), (_('Lowest'), low.vmin, low.start),
                                    (_('Highest'), high.vmax, high.start)):
            found.append([str(term), str(_('%(value)s at %(time)s') % {'value': _amount(chart, value),
                                                                      'time': _at(chart, moment)})])
    if chart.gaps:
        found.append([str(_('No value')), str(gap_text(chart))])
    return found


def data(chart, title, bands=None):
    """The chart as data for a browser chart (Tank › Water, Sensors › Charts, behind `?ui=next`): exactly what `draw`
    draws, never more and never less, as columns (times in seconds since 1970, UTC; the page shows them on `zone`):
    the buckets with their mean, lowest and highest, messages, channel, role and source; the gaps (never bridged); the
    manual and lab samples; the moves, calibrations and pH-scale changes; the notes; and the fish's limit bands of the
    quantity when it has any (`bands`: sensors.read.bands_of); the chart in words (`said`, `gap_text`) and the word for
    a bucket from a backup or the system's channel (`other_text`), which `draw` marks with a small circle. Numbers are as stored: the page rounds them to the
    quantity's decimals. Every word is translated here; nothing is worked out in the browser. `simulated`: the drawn
    buckets that come from the live demo's channels (sensors/demo.py `demo_channels`), and `simulated_text` to say so."""
    from .demo import demo_channels

    quantity = chart.quantity
    buckets = chart.buckets
    demo = demo_channels({b.channel_no for b in buckets})
    return {
        'head': head_text(chart, title), 'title': str(title),
        'quantity': {'code': quantity.code, 'label': str(quantity.label), 'unit': quantity.unit,
                     'decimals': quantity.decimals, 'water': quantity.water},
        'tier': chart.tier, 'tier_text': str(tier_text(chart.tier)), 'width_s': int(chart.width.total_seconds()),
        'width_text': str(width_text(chart.width)), 'start': _epoch(chart.start), 'end': _epoch(chart.end),
        'zone': getattr(chart.zone, 'key', str(chart.zone)), 'empty': chart.empty and not chart.samples,
        'empty_text': str(_('No sensor values in this time.')),
        'buckets': {'start': [_epoch(b.start) for b in buckets], 'end': [_epoch(b.end) for b in buckets],
                    'avg': [b.avg for b in buckets], 'min': [b.vmin for b in buckets], 'max': [b.vmax for b in buckets],
                    'n': [b.n for b in buckets], 'channel': [b.channel_no for b in buckets],
                    'role': [b.role for b in buckets], 'origin': [b.origin for b in buckets],
                    'other': [b.role == 'backup' or b.origin == read.SYSTEM_SENSOR for b in buckets],
                    'simulated': [b.channel_no in demo for b in buckets]},
        'simulated': bool(demo), 'simulated_text': str(_('Simulated values')) if demo else '',
        # a bucket from a backup channel or from the system's channel (`other`) is drawn as such, as `draw` does
        'other_text': str(_('From the backup or the system’s channel')),
        'said': said(chart), 'gap_text': str(gap_text(chart)),
        'gaps': [[_epoch(start), _epoch(end)] for start, end in chart.gaps],
        'samples': [{'at': _epoch(at), 'value': float(value), 'source': source} for at, value, source in chart.samples],
        'markers': [{'at': _epoch(marker.at), 'kind': marker.kind, 'channel': marker.channel_no,
                     'label': str(marker_text(marker))} for marker in chart.markers],
        'notes': [str(note) for note in notes(chart)],
        'bands': (bands or {}).get(quantity.code, {}),
    }
