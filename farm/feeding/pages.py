"""Operations › Feeding's read pages in the new look (behind `?ui=next`, core.ui.is_next): the Meal board and Records
(Feeding records, and By unit and day), drawn by the shared list page (island `list-page`, frontend/islands/ui/ListPage.tsx)
from props made here with core/listprops.py's words. Each page is read by its view in farm/feeding/views.py exactly as for
the classic page (the same rows, the same page of them, the same filters) and worded with the classic templates' msgids
(templates/farm/meal_board.html, _meal_board_table.html, feeding_list.html, _feeding_days.html), so core.pagesays holds
each new page to its old one.

Safety: a unit whose ration cannot be worked out says why where its next meal would be, never a figure; a temperature that
is not fresh is drawn stale with its warning; an estimate that ran too long says "Weigh now" / "Weigh soon" in its chip;
an estimate with days without an expected FCR says it is incomplete. Record meal and Record feeding open the feeding form
as a page (its own address), never the classic dialog."""
from django.template.defaultfilters import floatformat
from django.template.loader import render_to_string
from django.utils import formats
from django.utils.html import strip_tags
from django.utils.translation import gettext as _, ngettext

from core import listprops as L
from core.pagesays import squash

from .. import words
from ..stock.units_next import mix_chips, placement_chips
from ..templatetags.feeding import age, celsius, fcr, feed_kg, meal_pips, weights
from ..templatetags.stock import fish, grams, kilos, percent, tonnes

DASH = '—'
SFR_SAID = 'Specific feeding rate: the share of the body weight fed a day'
ESTIMATE_SAID = 'Estimated: the measured weight and the feed since, divided by the expected FCR'


def _day(day):
    return formats.date_format(day, 'DATE_FORMAT')


def _pellet(feed):
    """A feed's pellet size ("3 mm"), the classic template's words and figure (floatformat "-2"); '' without one."""
    if not feed.pellet_size_mm:
        return ''
    return _('%(size)s mm') % {'size': floatformat(feed.pellet_size_mm, '-2')}


def _department(unit, joint=', '):
    department = unit.production_department
    return department.name + (f'{joint}{department.site.name}' if department.site else '')


# ---- the meal board ------------------------------------------------------------------------------
def _next_meal(line):
    share, basis = line['share'], line['share'].end
    if basis.cleaner_fish:
        return L.cell(str(words.CLEANER_FISH_NO_FEEDING_TABLE_OF_THEIR))
    if line['why']:
        chips = [L.chip('hold', str(words.FASTING))] if basis.missing == 'fasting' else ()
        return L.cell(str(line['why']), chips=chips)
    if share.next_meal_kg is not None:
        band = basis.band
        sub = [band.feed.code + (f', {_pellet(band.feed)}' if band.feed.pellet_size_mm else '')] if band else ()
        return L.cell(feed_kg(share.next_meal_kg), figure=True, sub=sub)
    if share.remaining_kg is not None:
        return L.cell(str(words.MEALS_DONE))
    return L.cell(str(words.NO_DATA))


def _today(line):
    share, basis = line['share'], line['share'].end
    if basis.cleaner_fish or line['why']:
        return L.cell(DASH)
    states = meal_pips(share)
    sub = []
    if share.remaining_kg is not None:
        sub.append(_('%(kilos)s left') % {'kilos': feed_kg(share.remaining_kg)})
        if share.over_kg > 0:
            sub.append(_('%(kilos)s over the ration') % {'kilos': feed_kg(share.over_kg)})
    pips = L.pips(states, _('%(done)s of %(planned)s meals done') % {'done': share.meals, 'planned': share.planned_meals}) \
        if states else None
    return L.cell(sub[0] if sub else None, sub=sub[1:], pips=pips)


def _ration(line):
    share, basis = line['share'], line['share'].end
    if basis.cleaner_fish:
        return L.cell('–')
    if line['why']:
        return L.cell(str(words.NO_DATA))
    sfr = basis.sfr
    sub = [_('%(meals)s × %(meal)s') % {'meals': share.planned_meals, 'meal': feed_kg(share.meal_kg)},
           f"{str(words.SFR)} {percent(sfr.value, 2)}"]
    if sfr.interpolated:
        sub.append(_('%(low)s at %(low_t)s, %(high)s at %(high_t)s') % {
            'low': percent(sfr.low.sfr_pct, 2), 'low_t': celsius(sfr.low.temperature_c),
            'high': percent(sfr.high.sfr_pct, 2), 'high_t': celsius(sfr.high.temperature_c)})
    return L.cell(feed_kg(share.ration_kg), sub=sub)


def _batch(line):
    share = line['share']
    chips = [L.chip('neutral', str(words.CLEANER_FISH))] if line['cleaner'] else ()
    return L.cell(line['batch'].code, sub=[_('%(fish)s fish · %(biomass)s est.') % {
        'fish': fish(share.fish), 'biomass': kilos(share.biomass_kg)}], chips=chips)


def _weight(line):
    share = line['share']
    if share.last_weighed:
        said = _('%(weight)s weighed %(date)s') % {'weight': grams(share.measured_g), 'date': _day(share.last_weighed)}
    else:
        said = _('%(weight)s as stocked') % {'weight': grams(share.measured_g)}
    chips = []
    days = line['estimate_days']
    if line['drift'] == 'now':
        chips.append(L.chip('critical', ngettext('Weigh now: the estimate is %(days)s day old',
                                                 'Weigh now: the estimate is %(days)s days old', days) % {'days': days}))
    elif line['drift'] == 'soon':
        chips.append(L.chip('warning', ngettext('Weigh soon: %(days)s day since the last measured weight',
                                                'Weigh soon: %(days)s days since the last measured weight', days)
                            % {'days': days}))
    if share.blind_days:
        chips.append(L.chip('warning', ngettext(
            'Estimate incomplete: %(days)s feeding day without an expected FCR',
            'Estimate incomplete: %(days)s feeding days without an expected FCR', share.blind_days)
            % {'days': share.blind_days}))
    return L.cell(grams(share.end_g), sub=[said], chips=chips)


def _water(row):
    temperature = row['temperature']
    if not temperature:
        return L.cell(str(words.NO_DATA))
    if temperature.via == 'unit':
        where = _('unit, %(age)s ago') % {'age': age(temperature.age)}
    else:
        where = _('loop %(system)s, %(age)s ago') % {'system': temperature.point.code, 'age': age(temperature.age)}
    if temperature.fresh:
        return L.cell(celsius(temperature.value_c), sub=[where])
    # never drawn as fresh: the stale chip on the figure, and its warning ("Based on the temperature from …")
    return L.cell(chip=L.chip('stale', celsius(temperature.value_c)), sub=[where, str(words.STALE), temperature.warning])


def _protocol(line, unit):
    basis = line['share'].end
    if basis.protocol:
        if basis.scope == 'batch_in_unit':
            via = _('via %(batch)s in %(unit)s') % {'batch': line['batch'].code, 'unit': unit.code}
        elif basis.scope == 'unit':
            via = _('via unit %(unit)s') % {'unit': unit.code}
        else:
            via = _('via batch %(batch)s') % {'batch': line['batch'].code}
        sub = [via]
        if basis.band:
            feed = basis.band.feed
            sub.append(' · '.join(part for part in (str(weights(basis.band)), feed.code, _pellet(feed),
                                                    _('FCR %(fcr)s') % {'fcr': fcr(basis.fcr)}) if part))
        return L.cell(basis.protocol.name, sub=sub)
    if basis.cleaner_fish:
        return L.cell('–')
    return L.cell(str(words.NO_DATA))


def meal_board_props(request, context):
    """The Meal board's props from the view's `context` (the classic page's): a row per batch line of each unit with fish;
    the unit's own cells (its code, fed today, the water, Record meal) on its first line."""
    params, choices = context['params'], context['choices']
    columns = [L.column('unit', str(words.UNIT)), L.column('next', str(words.NEXT_MEAL)), L.column('today', str(words.TODAY)),
               L.column('fed', str(words.FED_TODAY), numeric=True), L.column('ration', str(words.RATION), numeric=True),
               L.column('batch', str(words.BATCH)), L.column('weight', str(words.AVG_WEIGHT), numeric=True),
               L.column('water', str(words.WATER)), L.column('protocol', str(words.PROTOCOL))]
    rows = []
    for row in context['rows']:
        unit, day = row['unit'], row['day']
        actions = []
        if row['record_url']:
            actions.append(L.link(row['record_url'], str(words.RECORD_MEAL), 'utensils', labelled=True))
        if row['water_url']:
            actions.append(L.link(row['water_url'], str(words.RECORD_WATER_SAMPLE), 'droplet'))
        chips, sub = mix_chips(row['mixes'])
        chips_more, sub_more = placement_chips(row['placements'])
        unit_cell = L.cell(unit.code, strong=True, chips=chips + chips_more, sub=[*sub, *sub_more, _department(unit)])
        fed = L.cell(feed_kg(day.fed_kg) if day else feed_kg(0), sub=[ngettext(
            '%(meals)s meal', '%(meals)s meals', day.meals_done) % {'meals': day.meals_done}] if day and day.feedings else ())
        for at, line in enumerate(row['lines']):
            first = at == 0
            status = 'critical' if line['drift'] == 'now' else (
                'warning' if line['drift'] == 'soon' or line['share'].blind_days
                or (first and row['temperature'] and not row['temperature'].fresh) else None)
            rows.append(L.row(f"{unit.pk}-{line['batch'].pk}", {
                'unit': unit_cell if first else L.cell(None),
                'next': _next_meal(line), 'today': _today(line),
                'fed': fed if first else L.cell(None),
                'ration': _ration(line), 'batch': _batch(line), 'weight': _weight(line),
                'water': _water(row) if first else L.cell(None),
                'protocol': _protocol(line, unit),
            }, actions if first else (), status=status))
    filters = []
    if len(choices['site']) > 1:
        filters.append(L.choice('site', str(words.SITE), params['site'],
                                [('', str(words.ALL_SITES)), *((site.pk, site.name) for site in choices['site'])]))
    filters.append(L.choice('department', str(words.PRODUCTION_DEPARTMENT), params['department'],
                            [('', str(words.ALL_PRODUCTION_DEPARTMENTS)),
                             *((item.pk, item.name) for item in choices['department'])]))
    if choices['system']:
        filters.append(L.choice('system', str(words.SYSTEM), params['system'],
                                [('', str(words.ALL_SYSTEMS)), *((item.pk, item.name) for item in choices['system'])]))
    how = str(words.THE_RATION_IS_THE_ESTIMATED_BIOMASS_TIMES)
    notices = [L.notice('flagged', 'warning', str(words.OVER_AND_UNDERFEEDING_ARE_NOT_FLAGGED_YET)),
               L.notice('how', 'neutral', f"{str(words.HOW_RATIONS_ARE_WORKED_OUT)}: {how}")]
    count = len(context['rows'])
    if context['filtered']:
        empty = {'title': str(words.NO_UNIT_WITH_FISH_MATCHES_THESE_FILTERS), 'text': None,
                 'link': {'href': context['clear_url'], 'label': str(words.CLEAR_FILTERS)}, 'add': None}
    else:
        empty = {'title': str(words.NO_UNIT_HOLDS_FISH), 'text': str(words.THE_BOARD_LISTS_THE_UNITS_WITH_FISH),
                 'link': None, 'add': None}
    lines = [ngettext('%(count)s unit', '%(count)s units', count) % {'count': count},
             f"{str(words.SFR)}: {_(SFR_SAID)}", f"{str(words.AVG_WEIGHT)}: {_(ESTIMATE_SAID)}"] if count else ()
    return L.page_props(request, label=context['title'], columns=columns, rows=rows, filters=filters, notices=notices,
                        lines=lines, empty=empty, table_label=str(words.MEAL_BOARD_SCROLLS_SIDEWAYS))


# ---- Records ---------------------------------------------------------------------------------------
def _views(context):
    return L.tabs(str(words.RECORDS), [(item['url'], item['label'], None, item['current']) for item in context['views']])


def _unit_choices(units):
    return [(unit.pk, f'{unit.code} · {unit.name}') for unit in units]


def _batch_choices(batches):
    return [(batch.pk, batch.code + (f' · {batch.name}' if batch.name else '')) for batch in batches]


def _record_link(context):
    return (context['record_url'], str(words.RECORD_FEEDING)) if context.get('record_url') else None


def records_props(request, context):
    """Feeding records: every feeding, newest first, voided ones struck through with who voided them and why."""
    params, choices = context['params'], context['choices']
    columns = [L.column('date', str(words.DATE)), L.column('unit', str(words.UNIT)), L.column('batches', str(words.BATCHES_FED)),
               L.column('feed', str(words.FEED)), L.column('given', str(words.FEED_GIVEN), numeric=True),
               L.column('meals', str(words.MEALS), numeric=True), L.column('feeder', str(words.FEEDER)),
               L.column('by', str(words.RECORDED_BY)), L.column('notes', str(words.NOTES))]
    from core.templatetags.dates import site_clock
    rows = []
    for row in context['rows']:
        record = row['record']
        unit = record.unit
        site = unit.production_department.site
        notes = []
        if record.high_rate_ack:
            notes.append(str(words.ABOVE_THE_USUAL_FEED_RATE_ACCEPTED))
        if record.is_deleted:
            notes.append(_('voided by %(name)s: %(reason)s') % {
                'reason': record.void_reason, 'name': record.deleted_by.get_username() if record.deleted_by else 'system'})
        feed = record.feed
        actions = [L.link(row['void_url'], str(words.VOID), 'x', danger=True, labelled=True)] if row['void_url'] else []
        rows.append(L.row(record.pk, {
            'date': L.cell(_day(record.date), sub=[formats.time_format(record.time, 'TIME_FORMAT') if record.time else ''],
                           chips=[L.chip('neutral', str(words.VOIDED))] if record.is_deleted else ()),
            'unit': L.cell(unit.code, strong=True, sub=[_department(unit, ' · ')]),
            'batches': L.cell(' + '.join(batch.code for batch in row['batches']) or DASH,
                              sub=[str(words.CLEANER_FISH) if record.target == 'cleaner_fish' else '']),
            'feed': L.cell(feed.name, sub=[feed.code + (f' · {_pellet(feed)}' if feed.pellet_size_mm else '')]),
            'given': L.cell(feed_kg(record.amount_kg)),
            'meals': L.cell(record.meals or DASH),
            'feeder': L.cell(record.feeder.name if record.feeder else DASH),
            'by': L.cell(record.created_by.get_username() if record.created_by else 'system',
                         sub=[formats.date_format(site_clock(record.created_at, site), 'DATETIME_FORMAT')]),
            'notes': L.cell(record.notes or None, sub=notes),
        }, actions, voided=record.is_deleted))
    filters = [
        L.choice('site', str(words.SITE), params['site'], [('', str(words.ALL_SITES)), *((s.pk, s.name) for s in choices['site'])]),
        L.choice('unit', str(words.UNIT), params['unit'], [('', str(words.ALL_UNITS)), *_unit_choices(choices['unit'])]),
        L.choice('batch', str(words.BATCH), params['batch'], [('', str(words.ALL_BATCHES)), *_batch_choices(choices['batch'])]),
        L.choice('feed', str(words.FEED), params['feed'], [('', str(words.ALL_FEEDS)), *((f.pk, str(f)) for f in choices['feed'])]),
        L.day('from', str(words.FROM), params['from']), L.day('to', str(words.TO), params['to']),
        L.check('voided', str(words.SHOW_VOIDED), params['voided']),
    ]
    if context['filtered']:
        empty = {'title': str(words.NO_FEEDING_MATCHES_THESE_FILTERS), 'text': None,
                 'link': {'href': context['clear_url'], 'label': str(words.CLEAR_FILTERS)}, 'add': None}
    else:
        empty = {'title': str(words.NO_FEEDING_RECORDED_YET), 'text': str(words.FEED_GIVEN_TO_A_UNIT_IS_RECORDED),
                 'link': None, 'add': None}
    return L.page_props(request, label=context['title'], tabs=_views(context), columns=columns, rows=rows,
                        filters=filters, add=_record_link(context), lines=[
                            f"{context['count_line']} · {tonnes(context['kilos'])}"],
                        empty=empty, page=context['page'], pager_query=context['pager_query'])


def _correction(item):
    """A weighing against the estimate it replaced, in the classic partial's words (farm/_correction.html, rendered)."""
    return squash(strip_tags(render_to_string('farm/_correction.html', {
        'correction': item['correction'], 'batch': item['batch']})))


def _shares(row):
    lines = []
    for item in row['shares']:
        share, basis = item['share'], item['share'].end
        head = f"{item['batch'].code} · " + _('%(fish)s fish at %(weight)s est.') % {
            'weight': grams(share.end_g), 'fish': fish(share.fish)}
        if basis.cleaner_fish:
            said = str(words.CLEANER_FISH_NO_FEEDING_TABLE_OF_THEIR)
        elif item['why']:
            said = str(item['why'])
        else:
            said = ngettext('%(protocol)s: %(sfr)s at %(temperature)s, %(meals)s meal',
                            '%(protocol)s: %(sfr)s at %(temperature)s, %(meals)s meals', share.planned_meals) % {
                'protocol': basis.protocol.name, 'sfr': percent(basis.sfr.value, 2),
                'temperature': celsius(basis.temperature.value_c), 'meals': share.planned_meals}
            if share.over_kg > 0:
                said += ' · ' + _('%(kilos)s over the ration') % {'kilos': feed_kg(share.over_kg)}
        lines += [head, said]
    return lines


def days_props(request, context):
    """Records by unit and day: per unit and day the calculated ration, the feed given and the deviation, each batch's
    estimated weight and the basis of its ration or why there is none; a weighing's correction on a row of its own."""
    params, choices = context['params'], context['choices']
    columns = [L.column('date', str(words.DATE)), L.column('unit', str(words.UNIT)), L.column('batches', str(words.BATCHES)),
               L.column('calculated', str(words.CALCULATED), numeric=True), L.column('given', str(words.GIVEN), numeric=True),
               L.column('deviation', str(words.DEVIATION), numeric=True)]
    rows = []
    for row in context['day_rows']:
        unit, unit_day = row['unit'], row['unit_day']
        lines = _shares(row)
        calculated = unit_day.calculated_kg if unit_day else None
        deviation = unit_day.deviation_kg if unit_day else None
        warn = any(item['why'] and not item['share'].end.cleaner_fish for item in row['shares'])
        rows.append(L.row(f'{unit.pk}-{row["day"].isoformat()}', {
            'date': L.cell(_day(row['day'])),
            'unit': L.cell(unit.code, strong=True, sub=[_department(unit, ' · ')]),
            'batches': L.cell(lines[0], sub=lines[1:]) if lines else L.cell(str(words.NO_FISH_AT_THE_END_OF_THE)),
            'calculated': L.cell(feed_kg(calculated) if calculated is not None else DASH),
            'given': L.cell(feed_kg(row['given_kg']), sub=[_('and %(kilos)s to the cleaner fish') % {
                'kilos': feed_kg(row['cleaner_kg'])} if row['cleaner_kg'] else '']),
            'deviation': L.cell(feed_kg(deviation), strong=True, sub=[percent(unit_day.deviation_pct, 1)
                                                                      if unit_day.deviation_pct is not None else ''])
            if deviation is not None else L.cell(DASH),
        }, status='warning' if warn else None))
        for at, item in enumerate(row['corrections']):
            rows.append(L.row(f'{unit.pk}-{row["day"].isoformat()}-c{at}', {
                'date': L.cell(None), 'unit': L.cell(None), 'batches': L.cell(_correction(item))}))
    filters = []
    if len(choices['site']) > 1:
        filters.append(L.choice('site', str(words.SITE), params['site'],
                                [('', str(words.ALL_SITES)), *((s.pk, s.name) for s in choices['site'])]))
    filters += [L.choice('unit', str(words.UNIT), params['unit'], [('', str(words.ALL_UNITS)), *_unit_choices(choices['unit'])]),
                L.choice('batch', str(words.BATCH), params['batch'], [('', str(words.ALL_BATCHES)), *_batch_choices(choices['batch'])]),
                L.day('from', str(words.FROM), params['from']), L.day('to', str(words.TO), params['to'])]
    notices = [L.notice('how', 'neutral', str(words.THE_CALCULATED_RATION_OF_A_DAY_COUNTS))]
    if context['clipped']:
        notices.append(L.notice('clipped', 'warning', ngettext(
            'A page shows at most %(days)s day: the first day was moved.',
            'A page shows at most %(days)s days: the first day was moved.', context['span']) % {'days': context['span']}))
    said = _('Given %(given)s') % {'given': feed_kg(context['given_kg'])}
    if context['calculated_kg'] is not None:
        said += ' · ' + _('calculated %(calculated)s') % {'calculated': feed_kg(context['calculated_kg'])}
    if context['cleaner_kg']:
        said += ' · ' + _('to the cleaner fish %(kilos)s') % {'kilos': feed_kg(context['cleaner_kg'])}
    if context['filtered']:
        empty = {'title': str(words.NO_UNIT_HELD_FISH_ON_THESE_DAYS_2), 'text': None,
                 'link': {'href': context['clear_url'], 'label': str(words.CLEAR_FILTERS)}, 'add': None}
    else:
        empty = str(words.NO_UNIT_HELD_FISH_ON_THESE_DAYS)
    return L.page_props(request, label=context['title'], tabs=_views(context), columns=columns, rows=rows,
                        filters=filters, keep=[('view', 'days')], add=_record_link(context), notices=notices,
                        lines=[said], empty=empty, page=context['page'], pager_query=context['pager_query'])



def choose_props(request, context):
    """Record feeding from Records (farm/feeding_choose.html): the units with fish, and those whose fish left on a day that
    may still be dated, each opening its feeding form as a page; a unit's fish in the classic partial's words
    (farm/_feeding_choice.html)."""
    rows = []
    for item in context['units']:
        unit = item['unit']
        department = unit.production_department
        said = squash(strip_tags(render_to_string('farm/_feeding_choice.html', {'item': item}, request=request)))
        rows.append(L.row(unit.pk, {
            # the classic link's line: the code, the unit's name, its department and site
            'unit': L.cell(' · '.join(part for part in (unit.code, unit.name, department.name,
                                                        department.site.name if department.site else '') if part),
                           href=item['url'], strong=True),
            'fish': L.cell(said or None)}))
    return L.page_props(request, label=context['heading'], columns=[L.column('unit', str(words.UNIT)),
                                                                     L.column('fish', str(words.FISH))],
                        rows=rows, notices=[L.notice('choose', 'neutral', str(words.CHOOSE_THE_UNIT_THAT_WAS_FED))],
                        empty={'title': str(words.NO_UNIT_HOLDS_FISH_A_FEEDING_NEEDS), 'text': None,
                               'link': {'href': context['back_url'], 'label': _('Cancel')}, 'add': None})
