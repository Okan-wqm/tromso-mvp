"""Operations › Harvest › Production plans › Growth plan (farm.harvest.views.production_plan): what the page of a
batch's plan says, once for both looks, and the plan as a file.

The page is the shared list page's props (core/listprops.py): the classic template (farm/production_plan.html) draws
the same props the new look's island draws, so the two looks cannot say different things. Its parts: where the plan
starts (today's estimate, or a measured point: link tabs), the lines above (the target and its day, the feed, the
economic FCR, the temperature read, the rules), the measured points beside the plan (a section), and the plan a week at
a time (the table). Every figure is farm/harvest/forecast.py's: nothing is worked out here but the economic FCR of a
day, by the growth rule's own function."""
import csv
from decimal import ROUND_HALF_UP, Decimal
from urllib.parse import urlencode

from django.http import HttpResponse
from django.utils import formats
from django.utils.translation import gettext as _

from core import listprops as L

from .. import words
from ..feeding.fold import PointKind
from ..feeding.growth import economic_fcr
from ..templatetags.feeding import celsius, difference, fcr, feed_kg
from ..templatetags.stock import fish, grams, kilos

DASH = '—'
START_WORDS = {PointKind.START: words.STOCKED, PointKind.WEIGHING: words.WEIGHED, PointKind.CLOSE: words.HARVESTED_OUT}


def _day(day):
    return formats.date_format(day, 'DATE_FORMAT')


def point_label(point):
    """Stocked 06.11.2026, Weighed 16.11.2026."""
    return f'{START_WORDS[point.kind]} {_day(point.day)}'


def _differences(grams_off, percent_off):
    return f'{difference(grams_off, 1)} g · {difference(percent_off, 1)} %'


def _measured_row(item):
    """A measured point beside the estimate it replaced (a weighing's correction) and beside the plan from the chosen
    start: the differences in g and %, the realised bFCR since the previous point against the expected FCR."""
    point, correction = item.point, item.point.correction
    how = [point.source.name] if point.source is not None else []
    if point.sample_count:
        how.append(_('%(fish)s fish weighed, %(kilos)s') % {'fish': fish(point.sample_count),
                                                           'kilos': kilos(point.sample_weight_kg)})
    estimated = planned = rates = L.cell(DASH)
    if correction is not None:
        estimated = L.cell(grams(correction.estimated_g),
                           sub=[_differences(correction.difference_g, correction.difference_pct)])
        if correction.realised_fcr or correction.expected_fcr:
            rates = L.cell(f'{fcr(correction.realised_fcr)} · {fcr(correction.expected_fcr)}')
    if item.planned_g is not None:
        planned = L.cell(grams(item.planned_g), sub=[_differences(item.difference_g, item.difference_pct)])
    return L.row(f'measured-{point.day.isoformat()}-{point.kind}', {
        'date': L.cell(point_label(point)), 'measured': L.cell(grams(point.avg_weight_g), strong=True, sub=how),
        'fish': L.cell(fish(point.fish)), 'estimated': estimated, 'planned': planned, 'fcr': rates})


def _plan_row(point):
    if point.fasting:
        rate = L.cell(DASH, sub=[str(words.FASTING_DAY)])
    else:
        rate = L.cell(fcr(point.fcr), sub=[f'{words.ECONOMIC_FCR} {fcr(economic_fcr(point.fcr, point.uneaten_pct))}'])
    return L.row(f'day-{point.day.isoformat()}', {
        'date': L.cell(_day(point.day)), 'weight': L.cell(grams(point.weight_g), strong=True),
        'fish': L.cell(fish(point.fish)), 'biomass': L.cell(kilos(point.biomass_kg)),
        'feed': L.cell(feed_kg(point.feed_kg)), 'to_date': L.cell(feed_kg(point.feed_to_date_kg)),
        'eaten': L.cell(feed_kg(point.eaten_kg)), 'uneaten': L.cell(feed_kg(point.uneaten_kg)), 'fcr': rate,
        'temperature': L.cell(celsius(point.temperature_c))})


def lines(unit, batch, target_g, found):
    """What a growth plan says above its tables: where it starts, the target and the day it is reached (or why not), the
    feed and the economic FCR of the days planned, what the temperature was read from, and the rules it follows."""
    forecast, curve = found.forecast, found.forecast.curve
    start = point_label(found.chosen) if found.chosen is not None else str(words.TODAYS_ESTIMATE)
    said = [_('%(unit)s · %(batch)s: %(fish)s fish at %(weight)s on %(date)s (%(start)s).') % {
        'unit': unit.code, 'batch': batch.code, 'fish': fish(forecast.fish), 'weight': grams(forecast.now_g),
        'date': _day(forecast.start), 'start': start}]
    if target_g is None:
        said.append(_('No target weight is set: the plan runs %(days)d days ahead.') % {'days': forecast.horizon_days})
    elif forecast.reached:
        said.append(_('Target %(target)s: reached on %(date)s.') % {'target': grams(target_g),
                                                                   'date': _day(forecast.day)})
    else:
        said.append(_('Target %(target)s: %(why)s') % {'target': grams(target_g), 'why': forecast.why})
    if target_g is None and curve.why:
        said.append(curve.why)
    if forecast.planned:
        said.append(_('Feed over these days: %(feed)s given, %(eaten)s eaten, %(uneaten)s uneaten; economic FCR of the '
                      'period %(fcr)s; %(fish)s fish and %(biomass)s at the end.') % {
            'feed': feed_kg(curve.feed_kg), 'eaten': feed_kg(curve.eaten_kg), 'uneaten': feed_kg(curve.uneaten_kg),
            'fcr': fcr(curve.economic_fcr), 'fish': fish(curve.end_fish),
            'biomass': kilos(curve.end_g * curve.end_fish / 1000)})
        if forecast.monthly:
            said.append(_('Every day at the site’s water temperature of its month (Setup › Sites).'))
        else:
            said.append(_('Every day at %(temperature)s, the unit’s latest temperature at the start, held.') % {
                'temperature': celsius(forecast.temperature_c)})
    return [*said, str(words.THE_PLAN_AHEAD_COUNTS), str(words.THE_SFR_IS_ITS_BANDS)]


def props(request, context):
    """The page's props from the view's context: the starts as link tabs, the lines, the measured points beside the plan
    as a section, the plan a week at a time, and the links to the file and back to the list."""
    found, forecast = context['plan'], context['plan'].forecast
    starts = [(context['url'], str(words.TODAYS_ESTIMATE), None, found.chosen is None)] + [
        (f"{context['url']}?{urlencode({'from': item.point.day.isoformat()})}", point_label(item.point), None,
         found.chosen is not None and found.chosen.day == item.point.day)
        for item in found.measured if item.point.day < found.today and item.point.kind != PointKind.CLOSE]
    measured = L.section('measured', words.MEASURED_AGAINST_THE_PLAN, [
        L.column('date', str(words.DATE)), L.column('measured', str(words.MEASURED), numeric=True),
        L.column('fish', str(words.FISH), numeric=True),
        L.column('estimated', str(words.ESTIMATED_BEFORE_IT), numeric=True),
        L.column('planned', str(words.PLANNED_THAT_DAY), numeric=True),
        L.column('fcr', str(words.FCR_REALISED_EXPECTED), numeric=True)],
        [_measured_row(item) for item in found.measured],
        lines=[] if found.measured else [str(words.NO_MEASURED_POINT_YET)])
    columns = [L.column('date', str(words.DATE)), L.column('weight', str(words.AVG_WEIGHT), numeric=True),
               L.column('fish', str(words.FISH), numeric=True), L.column('biomass', str(words.BIOMASS), numeric=True),
               L.column('feed', str(words.FEED_THAT_DAY), numeric=True),
               L.column('to_date', str(words.FEED_TO_DATE), numeric=True),
               L.column('eaten', str(words.EATEN), numeric=True), L.column('uneaten', str(words.UNEATEN), numeric=True),
               L.column('fcr', str(words.FCR_IN_FORCE), numeric=True),
               L.column('temperature', str(words.TEMPERATURE), numeric=True)]
    notices = [L.notice('file', 'neutral', str(words.THE_TABLE_SHOWS_ONE_DAY_A_WEEK),
                        link=(context['csv_url'], str(words.DOWNLOAD_EVERY_DAY_CSV)),
                        more=[(context['back_url'], str(words.BACK_TO_PRODUCTION_PLANS))])]
    return L.page_props(request, label=context['title'], tabs=L.tabs(str(words.PLAN_FROM), starts), columns=columns,
                        rows=[_plan_row(point) for point in forecast.weekly()], notices=notices,
                        lines=lines(context['unit'], context['batch'], context['target_g'], found),
                        empty=str(words.NO_DAY_IS_PLANNED), sections=[measured])


# ---- the file -------------------------------------------------------------------------------------------
COLUMNS = ('date', 'average_weight_g', 'fish', 'biomass_kg', 'feed_kg', 'feed_to_date_kg', 'eaten_kg', 'uneaten_kg',
           'fcr', 'economic_fcr', 'uneaten_pct', 'temperature_c', 'fasting')


def _plain(value, places):
    """A figure of the file: a decimal point, no grouping, rounded half up; empty when there is none."""
    return '' if value is None else f'{Decimal(value).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP):f}'


def csv_response(unit, batch, found):
    """Every day of a growth plan as a file: the start, then a row per day ahead. Its column names and figures are for a
    spreadsheet or a program: English names, a decimal point, ISO dates, whatever the reader's language."""
    forecast = found.forecast
    response = HttpResponse(content_type='text/csv; charset=utf-8', headers={
        'Content-Disposition': f'attachment; filename="growth-plan-{unit.code}-{batch.code}.csv"'})
    writer = csv.writer(response)
    writer.writerow(COLUMNS)
    writer.writerow([forecast.start.isoformat(), _plain(forecast.now_g, 4), _plain(forecast.fish, 0),
                     _plain(forecast.now_g * forecast.fish / 1000, 3), '', _plain(0, 3), '', '', '', '', '', '', ''])
    for point in forecast.curve.points:
        fed = not point.fasting
        writer.writerow([
            point.day.isoformat(), _plain(point.weight_g, 4), _plain(point.fish, 0), _plain(point.biomass_kg, 3),
            _plain(point.feed_kg, 3), _plain(point.feed_to_date_kg, 3), _plain(point.eaten_kg, 3),
            _plain(point.uneaten_kg, 3), _plain(point.fcr, 3),
            _plain(economic_fcr(point.fcr, point.uneaten_pct) if fed else None, 3),
            _plain(point.uneaten_pct if fed else None, 2), _plain(point.temperature_c, 1), '' if fed else 'yes'])
    return response
