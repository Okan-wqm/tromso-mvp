"""Operations › Health's read pages in the new look (behind `?ui=next`, core.ui.is_next): Treatments and Sea-lice counts,
drawn by the shared list page (island `list-page`, core/listprops.py) from props made here. Each page is read by its view
in farm/health/views.py exactly as for the classic page (the same rows, the same page of them, the same filters) and
worded with the classic templates' msgids (templates/farm/treatment_list.html, lice_list.html), so core.pagesays holds
each new page to its old one.

Food safety: the withdrawal a treatment puts on each batch is said in the server's own words (farm.handling.withdrawal:
`held_until`, and why it holds: `withdrawal_reason`), a batch held today in the hold chip; the unresolved old courses
(an unknown end that no longer holds the fish) are a warning above the list, each with what gives it an end. A site's
weekly lice average at or over its limit says "Over the limit" in a critical chip, with the limit beside it."""
from django.template.defaultfilters import floatformat
from django.utils import formats
from django.utils.translation import gettext as _, ngettext

from core import listprops as L
from core.templatetags.dates import company_clock, site_clock

from ..templatetags.health import held_until, lice, per_fish, unit_voidable, withdrawal_reason

DASH = '—'


def _day(day):
    return formats.date_format(day, 'DATE_FORMAT')


def _voided(record):
    return _('voided by %(name)s: %(reason)s') % {
        'reason': record.void_reason, 'name': record.deleted_by.get_username() if record.deleted_by else 'system'}


# ---- Treatments ------------------------------------------------------------------------------------
def _days(treatment, today):
    sub = []
    if treatment.end_date != treatment.start_date:
        sub.append(_('to %(date)s') % {'date': _day(treatment.end_date)})
    # the classic page's "Running" (its context has no `today`, so it never says it: the same here)
    chips = [L.chip('accent', _('Running'))] if today is not None and treatment.end_date > today else []
    return L.cell(_day(treatment.start_date), sub=sub, chips=chips)


def _units(treatment):
    units = list(treatment.units.all())
    if not units:
        return L.cell(DASH)
    site = units[0].production_department.site
    return L.cell(', '.join(unit.code for unit in units), strong=True, sub=[site.name if site else ''])


def _treatment(treatment):
    medicine = treatment.medicine
    sub = []
    said = [treatment.get_method_display(), medicine.active_substance] if medicine else []
    said.append(treatment.get_reason_display())
    if treatment.bath_minutes:
        said.append(_('%(minutes)s min') % {'minutes': treatment.bath_minutes})
    sub.append(' · '.join(str(part) for part in said))
    if treatment.health_event:
        sub.append(str(treatment.health_event))
    return L.cell(medicine.name if medicine else treatment.get_method_display(), sub=sub)


def _dose(treatment):
    dose = (f'{floatformat(treatment.dose_value, "-3")} {treatment.get_dose_unit_display()}'
            if treatment.dose_value is not None else DASH)
    amount = (f'{floatformat(treatment.amount_value, "-3")} {treatment.get_amount_unit_display()}'
              if treatment.amount_value is not None else '')
    return L.cell(dose, sub=[amount])


def _batches(parts):
    """Each batch the treatment reached, where, and the withdrawal it puts on it in the server's words (until when, and
    why); a batch held today in the hold chip."""
    if not parts:
        return L.cell(_('No fish found in these units on these days'))
    lines, chips = [], []
    for part in parts:
        line = part.batch.code
        if part.where:
            line += ' (' + ', '.join(part.where) + (f", {_('shared a unit')}" if part.shared else '') + ')'
        if part.withdrawal:
            line += f' · {held_until(part.withdrawal)}'
            lines += [line, str(withdrawal_reason(part.withdrawal))]
            if part.held:
                chips.append(L.chip('hold', part.batch.code))
        else:
            lines.append(line)
    return L.cell(lines[0], sub=lines[1:], chips=chips)


def _prescription(treatment):
    return L.cell(treatment.prescribed_by or DASH,
                  sub=[treatment.prescription_ref or '', treatment.vet.name if treatment.vet else ''])


def _by(treatment):
    sub = [formats.date_format(company_clock(treatment.created_at), 'DATETIME_FORMAT'), treatment.notes or '']
    if treatment.is_deleted:
        sub.append(_voided(treatment))
    chips = [L.chip('critical', _('Handling warning acknowledged'))] if treatment.acknowledgements.all() else ()
    return L.cell(treatment.created_by.get_username() if treatment.created_by else 'system', sub=sub, chips=chips)


def treatments_props(request, context):
    """Treatments: every treatment, newest first, the batches it reached and the withdrawal it puts on each."""
    params, choices, today = context['params'], context['choices'], context.get('today')
    columns = [L.column('days', _('Days')), L.column('units', _('Units')), L.column('treatment', _('Treatment')),
               L.column('dose', _('Dose · amount')), L.column('batches', _('Batches and withdrawal')),
               L.column('prescription', _('Prescription')), L.column('by', _('Recorded by'))]
    rows = []
    for row in context['rows']:
        treatment = row['treatment']
        actions = []
        if not treatment.is_deleted:
            if row['last_day_url']:
                actions.append(L.link(row['last_day_url'], _('Last day'), 'calendar', labelled=True))
            if row['void_url'] and unit_voidable(treatment):
                actions.append(L.link(row['void_url'], _('Void'), 'x', danger=True, labelled=True))
        held = any(part.held for part in row['batches'])
        days = _days(treatment, today)
        if treatment.is_deleted:
            days['chips'].append(L.chip('neutral', _('Voided')))
        rows.append(L.row(treatment.pk, {
            'days': days, 'units': _units(treatment), 'treatment': _treatment(treatment), 'dose': _dose(treatment),
            'batches': _batches(row['batches']), 'prescription': _prescription(treatment), 'by': _by(treatment),
        }, actions, voided=treatment.is_deleted, status='warning' if held and not treatment.is_deleted else None))
    filters = [
        L.choice('site', _('Site'), params['site'], [('', _('All sites')), *((s.pk, s.name) for s in choices['site'])]),
        L.choice('unit', _('Unit'), params['unit'],
                 [('', _('All units')), *((u.pk, f'{u.code} · {u.name}') for u in choices['unit'])]),
        L.choice('batch', _('Batch'), params['batch'], [('', _('All batches')), *(
            (b.pk, b.code + (f' · {b.name}' if b.name else '')) for b in choices['batch'])]),
        L.choice('method', _('Method'), params['method'], [('', _('All methods')), *choices['method']]),
        L.choice('medicine', _('Medicine'), params['medicine'],
                 [('', _('All medicines')), *((m.pk, m.name) for m in choices['medicine'])]),
        L.choice('show', _('Show'), params['show'], [('', _('All treatments')),
                                                     (context['under_withdrawal'], _('Under withdrawal today')),
                                                     (context['vaccinations'], _('Vaccinations'))]),
        L.day('from', _('From'), params['from']), L.day('to', _('To'), params['to']),
        L.check('voided', _('Show voided'), params['voided']),
    ]
    notices = []
    if context['unresolved']:
        days = context['unknown_days']
        notices.append(L.notice('unresolved', 'warning', ' '.join([_('Unresolved old courses') + ':', ngettext(
            'The end of these withdrawals is unknown and the course is older than %(days)s day: the fish are no longer '
            'held (Platform settings). Give each an end.',
            'The end of these withdrawals is unknown and the course is older than %(days)s days: the fish are no longer '
            'held (Platform settings). Give each an end.', days) % {'days': days}])))
        notices += [L.notice(f'unresolved-{at}', 'warning', text) for at, text in enumerate(context['unresolved'])]
    if context['filtered']:
        empty = {'title': _('No treatment matches these filters.'), 'text': None,
                 'link': {'href': context['clear_url'], 'label': _('Clear filters')}, 'add': None}
    else:
        empty = {'title': _('No treatment recorded yet'), 'text': _(
            'A bath, a medicated feed, an injection or a vaccination, or a treatment without a medicine, is recorded here '
            'or from a unit’s drawer on Production units.'), 'link': None, 'add': None}
    return L.page_props(request, label=context['title'], columns=columns, rows=rows, filters=filters, notices=notices,
                        add=(context['record_url'], _('Record treatment')) if context['record_url'] else None,
                        lines=[context['count_line']], empty=empty, page=context['page'],
                        pager_query=context['pager_query'])


# ---- Sea-lice counts --------------------------------------------------------------------------------
def _week_row(week):
    counted = ', '.join(count.unit.code for count in week.counts)
    sub = []
    if week.stocked:
        sub.append(_('%(counted)s of %(stocked)s units with fish now') % {'counted': len(week.counts),
                                                                          'stocked': week.stocked})
    if week.small_samples:
        sub.append(_('Fewer than %(fish)s fish examined in:') % {'fish': week.minimum_fish} + ' '
                   + ', '.join(count.unit.code for count in week.small_samples))
    over = [L.chip('critical', _('Over the limit'))] if week.over_limit else ()
    return L.row(f'{week.site.pk if week.site else "none"}-{week.year}-{week.week}', {
        'week': L.cell(_('Week %(week)s, %(year)s') % {'week': week.week, 'year': week.year}, strong=True),
        'site': L.cell(week.site.name if week.site else DASH, sub=[
            _('Area not set: the stricter limit applies (Facility › Sites)') if week.area_unknown else '']),
        'adult': L.cell(lice(week.adult_females), strong=bool(week.over_limit), chips=over),
        'limit': L.cell(lice(week.limit)),
        'mobile': L.cell(lice(week.mobile)), 'attached': L.cell(lice(week.attached)),
        'units': L.cell(counted or None, sub=sub),
    }, status='critical' if week.over_limit else ('warning' if week.small_samples else None))


def _count_row(row):
    count = row['count']
    unit = count.unit
    department = unit.production_department
    sub = [formats.date_format(site_clock(count.created_at, department.site), 'DATETIME_FORMAT'), count.notes or '']
    if count.is_deleted:
        sub.append(_voided(count))
    actions = [L.link(row['void_url'], _('Void'), 'x', danger=True, labelled=True)] \
        if row['void_url'] and unit_voidable(count) else []

    def stage(name, value):
        return L.cell(value, sub=[_('%(value)s per fish') % {'value': per_fish(count, name)}])
    return L.row(count.pk, {
        'date': L.cell(_day(count.date), chips=[L.chip('neutral', _('Voided'))] if count.is_deleted else ()),
        'unit': L.cell(unit.code, strong=True, sub=[department.name + (
            f' · {department.site.name}' if department.site else '')]),
        'fish': L.cell(count.fish_counted),
        'adult': stage('adult_females', count.adult_females), 'mobile': stage('mobile', count.mobile),
        'attached': stage('attached', count.attached),
        'by': L.cell(count.created_by.get_username() if count.created_by else 'system', sub=sub),
    }, actions, voided=count.is_deleted)


def lice_props(request, context):
    """Sea-lice counts: the sites' weekly averages against the statutory limit (a section above the list), then every
    count."""
    params, choices = context['params'], context['choices']
    weeks = None
    if context['weeks']:
        shown = context['weeks_shown']
        weeks = L.section('weeks', _('Weekly averages'), [
            L.column('week', _('Week')), L.column('site', _('Site')),
            L.column('adult', _('Adult females per fish'), numeric=True), L.column('limit', _('Limit'), numeric=True),
            L.column('mobile', _('Mobile per fish'), numeric=True),
            L.column('attached', _('Attached per fish'), numeric=True), L.column('units', _('Units counted'))],
            [_week_row(week) for week in context['weeks']], lines=[' '.join([ngettext(
                'The latest week of counts, per site.', 'The latest %(weeks)s weeks of counts, per site.', shown)
                % {'weeks': shown}, _(
                'A site averages the averages of its units counted that week, every unit weighing the same, and must '
                'stay below the limit: 0.5 adult female lice per fish, 0.2 in the spring weeks (lakselusforskriften § 8 '
                'and Vedlegg 1). The latest count of each unit in the week counts.')])])
    columns = [L.column('date', _('Date')), L.column('unit', _('Unit')), L.column('fish', _('Fish examined'), numeric=True),
               L.column('adult', _('Adult females'), numeric=True), L.column('mobile', _('Mobile'), numeric=True),
               L.column('attached', _('Attached'), numeric=True), L.column('by', _('Recorded by'))]
    filters = [
        L.choice('site', _('Site'), params['site'], [('', _('All sites')), *((s.pk, s.name) for s in choices['site'])]),
        L.choice('unit', _('Unit'), params['unit'],
                 [('', _('All units')), *((u.pk, f'{u.code} · {u.name}') for u in choices['unit'])]),
        L.day('from', _('From'), params['from']), L.day('to', _('To'), params['to']),
        L.check('voided', _('Show voided'), params['voided']),
    ]
    if context['filtered']:
        empty = {'title': _('No count matches these filters.'), 'text': None,
                 'link': {'href': context['clear_url'], 'label': _('Clear filters')}, 'add': None}
    else:
        empty = {'title': _('No sea-lice count recorded yet'), 'text': _(
            'Lice are counted at least every 7 days at 4 °C or above, every 14 days below (lakselusforskriften § 6).'),
                 'link': None, 'add': None}
    props = L.page_props(request, label=context['title'], columns=columns, rows=[_count_row(row) for row in context['rows']],
                         filters=filters, add=(context['record_url'], _('Record sea-lice count'))
                         if context['record_url'] else None, lines=[context['count_line']], empty=empty,
                         page=context['page'], pager_query=context['pager_query'], sections=[weeks] if weeks else ())
    return props
