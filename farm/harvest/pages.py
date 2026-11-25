"""Operations › Harvest › Harvested in the new look (behind `?ui=next`, core.ui.is_next): the harvests on the shared list
page (island `list-page`, core/listprops.py), read by farm.harvest.views.harvests exactly as for the classic page (the
same rows, the same page, the same filters) and worded with templates/farm/harvests.html's and _harvest_totals.html's
msgids, so core.pagesays holds the new page to the old one.

The classic page draws its totals per batch and per site under the table; the design draws them as two more views of the
page, "Per batch" and "Per site" (`?view=batch|site`, the filters kept), each a table of the same totals
(farm.harvest.read.totals over the same live rows). The classic page reads no `view`, so it is unchanged. The strip of the
Harvest group's pages (Harvested, Harvest plan, Production plans) stays the server's (farm/_harvest_tabs.html above
the island)."""
from urllib.parse import urlencode

from django.utils import formats
from django.utils.translation import gettext as _, pgettext

from core import listprops as L
from core.templatetags.dates import company_clock

from ..templatetags.harvest import signed_kilos, signed_percent
from ..templatetags.stock import fish, grams, kilos, signed, tonnes

DASH = '—'
VIEWS = ('', 'batch', 'site')
ROUND_SAID = 'The live weight as weighed at the harvest, before bleeding and gutting'
BOOK_SAID = 'What the stock book took out for these fish: their batch’s average in the unit, the last fish the rest of the book'


def _views(request, view):
    """Harvests, Per batch, Per site: each keeping the filters the address holds."""
    kept = {key: value for key, value in request.GET.items() if key not in ('view', 'page')}

    def href(name):
        query = urlencode({**kept, **({'view': name} if name else {})})
        return f'?{query}' if query else request.path
    return L.tabs(_('Harvest'), [(href(''), _('Harvests'), None, view == ''),
                                 (href('batch'), _('Per batch'), None, view == 'batch'),
                                 (href('site'), _('Per site'), None, view == 'site')])


def _harvest_row(row):
    harvest = row['harvest']
    operation, book, record = harvest.operation, harvest.book, harvest.record
    unit = harvest.unit
    notes = []
    if harvest.plan:
        notes.append(_('Planned for %(date)s') % {'date': formats.date_format(harvest.plan.date, 'DATE_FORMAT')})
    chips = []
    if harvest.acknowledged:
        chips.append(L.chip('critical', _('Handling warning acknowledged')))
        notes.append(' '.join(str(ack.get_warning_display()) for ack in harvest.acknowledged))
    if operation.is_deleted:
        notes.append(_('voided by %(name)s: %(reason)s') % {
            'reason': operation.void_reason,
            'name': operation.deleted_by.get_username() if operation.deleted_by else 'system'})
    transport = record.transport.name if record and record.transport else DASH
    actions = [L.link(row['void_url'], _('Void'), 'x', danger=True, labelled=True)] if row['void_url'] else []
    return L.row(operation.pk, {
        'date': L.cell(formats.date_format(operation.date, 'DATE_FORMAT'),
                       chips=[L.chip('neutral', _('Voided'))] if operation.is_deleted else ()),
        'unit': L.cell(unit.code, strong=True, sub=[unit.production_department.name + (
            f' · {harvest.site.name}' if harvest.site else '')]),
        'batch': L.cell(harvest.batch.code, sub=[harvest.batch.species.common_name]),
        'fish': L.cell(fish(harvest.fish)),
        'round': L.cell(kilos(harvest.weighed_kg)),
        'average': L.cell(grams(harvest.avg_weight_g)),
        'book': L.cell(kilos(book.kg if book else None)),
        'difference': L.cell(signed_kilos(book.difference_kg), sub=[signed_percent(book.difference_pct)])
        if book else L.cell(DASH),
        'loss': L.cell(_('%(fish)s fish') % {'fish': signed(harvest.loss.count_delta)},
                       sub=[kilos(harvest.loss_book.kg)]) if harvest.loss else L.cell(DASH),
        'facility': L.cell(record.facility.name, sub=[record.facility.approval_number]) if record else L.cell(DASH),
        'transport': L.cell(transport, sub=[record.vessel if record and record.vessel else '']),
        'by': L.cell(operation.created_by.get_username() if operation.created_by else 'system',
                     sub=[formats.date_format(company_clock(operation.created_at), 'DATETIME_FORMAT')]),
        'notes': L.cell(operation.notes or None, sub=notes, chips=chips),
    }, actions, voided=operation.is_deleted)


def _total_row(total):
    return L.row(f'total-{total.label}', {
        'label': L.cell(total.label, strong=True),
        'harvests': L.cell(total.harvests), 'fish': L.cell(fish(total.fish)),
        'round': L.cell(kilos(total.weighed_kg)), 'average': L.cell(grams(total.avg_weight_g)),
        'book': L.cell(kilos(total.book_kg)),
        'difference': L.cell(signed_kilos(total.difference_kg), sub=[signed_percent(total.difference_pct)]),
    })


def harvests_props(request, context):
    """The props of Harvested from the view's `context` (the classic page's): the harvests, or (`?view=`) the totals per
    batch or per site of the same live rows."""
    params, choices = context['params'], context['choices']
    view = request.GET.get('view', '')
    view = view if view in VIEWS else ''
    grand = context['grand']
    said = context['count_line'] + (' · ' + _('%(weighed)s round weight, %(book)s in the book') % {
        'weighed': tonnes(grand.weighed_kg), 'book': tonnes(grand.book_kg)} if grand else '')
    totals = [L.column('harvests', _('Harvests'), numeric=True), L.column('fish', _('Fish'), numeric=True),
              L.column('round', _('Round weight'), numeric=True), L.column('average', _('Avg. weight'), numeric=True),
              L.column('book', _('Book'), numeric=True), L.column('difference', _('Difference'), numeric=True)]
    if view:
        caption = _('Per batch') if view == 'batch' else _('Per site')
        columns = [L.column('label', caption), *totals]
        rows = [_total_row(total) for total in context['by_batch' if view == 'batch' else 'by_site']]
        page = None
    else:
        columns = [L.column('date', _('Date')), L.column('unit', _('Unit')), L.column('batch', _('Batch')),
                   L.column('fish', _('Fish'), numeric=True), L.column('round', _('Round weight'), numeric=True),
                   L.column('average', _('Avg. weight'), numeric=True), L.column('book', _('Book'), numeric=True),
                   L.column('difference', _('Difference'), numeric=True),
                   L.column('loss', _('Unaccounted loss'), numeric=True),
                   L.column('facility', _('Slaughter facility')), L.column('transport', _('Transport')),
                   L.column('by', _('Recorded by')), L.column('notes', _('Notes'))]
        rows = [_harvest_row(row) for row in context['rows']]
        page = context['page']
    filters = [
        L.choice('site', _('Site'), params['site'], [('', _('All sites')), *((s.pk, s.name) for s in choices['site'])]),
        L.choice('department', _('Production department'), params['department'],
                 [('', _('All production departments')), *((d.pk, d.name) for d in choices['department'])]),
        L.choice('unit', _('Unit'), params['unit'],
                 [('', _('All units')), *((u.pk, f'{u.code} · {u.name}') for u in choices['unit'])]),
        L.choice('batch', _('Batch'), params['batch'], [('', _('All batches')), *(
            (b.pk, b.code + (f' · {b.name}' if b.name else '')) for b in choices['batch'])]),
        L.choice('species', pgettext('singular', 'Species'), params['species'],
                 [('', _('All species')), *((s.pk, s.common_name) for s in choices['species'])]),
        L.choice('facility', _('Slaughter facility'), params['facility'],
                 [('', _('All slaughter facilities')), *((f.pk, f.name) for f in choices['facility'])]),
        L.day('from', _('From'), params['from']), L.day('to', _('To'), params['to']),
        L.check('voided', _('Show voided'), params['voided']),
    ]
    if context['filtered']:
        empty = {'title': _('No harvest matches these filters.'), 'text': None,
                 'link': {'href': context['clear_url'], 'label': _('Clear filters')}, 'add': None}
    else:
        empty = {'title': _('No harvest recorded yet'), 'text': _(
            'A harvest is recorded from its unit’s drawer on Production units, or from its plan.'), 'link': None, 'add': None}
    lines = [said]
    if not view and rows:
        lines += [f"{_('Round weight')}: {_(ROUND_SAID)}", f"{_('Book')}: {_(BOOK_SAID)}"]
    return L.page_props(request, label=context['title'], tabs=_views(request, view), columns=columns, rows=rows,
                        filters=filters, keep=[('view', view)] if view else (), lines=lines, empty=empty, page=page,
                        pager_query=context['pager_query'])
