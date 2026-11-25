"""The new look's lists (core/listprops.py, island `list-page`) of Operations › Feeding's two tabs, Protocols and
Assignments (farm/resources/feeding_protocol.py: `list_rows`, `list_filters`), worded as their classic templates word them
(templates/farm/feeding_protocol_list.html, protocol_assignment_list.html: the same msgids) from the rows and the context
the one list view (core.crud.ListView) read for the classic page."""
from django.template.defaultfilters import floatformat, truncatechars
from django.utils import formats
from django.utils.translation import gettext as _, ngettext, pgettext

from core import listprops as L

from ..words import WORDS

from ..templatetags.feeding import celsius, fcr, weights
from ..templatetags.stock import fish

DASH = '—'
PROTOCOL_CHIP = {'active': 'ok', 'draft': 'neutral', 'retired': 'neutral'}


def protocol_filters(view, context):
    return [L.choice('species', pgettext('singular', 'Species'), context['chosen_species'],
                     [('', _('All species')), *((each.pk, each.common_name) for each in context['species_list'])]),
            L.choice('status', _('Status'), context['chosen_status'], [('', _('All statuses')), *context['statuses']])]


def _band(band):
    feed = band.feed
    pellet = _('%(size)s mm') % {'size': floatformat(feed.pellet_size_mm, '-2')} if feed.pellet_size_mm else ''
    return ' · '.join(part for part in (str(weights(band)), feed.code, pellet) if part)


def _temperatures(protocol):
    columns = protocol.columns()
    if not columns:
        return L.cell(DASH)
    return L.cell(f'{celsius(columns[0])} – {celsius(columns[-1])}', sub=[ngettext(
        '%(count)s column', '%(count)s columns', len(columns)) % {'count': len(columns)}])


def protocols(view, objects, context):
    """Protocols: each with its species, its status, its bands (weights, feed, pellet), its temperature columns, the FCR
    it expects and its assignments in force today."""
    rows = []
    for protocol in objects:
        bands = [_band(band) for band in protocol.bands.all()]
        rows.append(L.row(protocol.pk, {
            'protocol': L.title(view, context, protocol, protocol.name,
                                sub=[truncatechars(protocol.notes, 80) if protocol.notes else '']),
            'species': L.cell(protocol.species.common_name),
            'status': L.cell(chip=L.chip(PROTOCOL_CHIP.get(protocol.status, 'neutral'), protocol.get_status_display())),
            'bands': L.cell(bands[0], sub=bands[1:]) if bands else L.cell(_('No table yet')),
            'temperatures': _temperatures(protocol),
            'fcr': L.cell(fcr(protocol.expected_fcr)),
            'in_force': L.cell(protocol.in_force or DASH),
        }, L.edit_delete(view, context, protocol, protocol.name)))
    return {
        'columns': [L.column('protocol', _('Protocol')), L.column('species', pgettext('singular', 'Species')),
                    L.column('status', _('Status')), L.column('bands', _('Weight bands')),
                    L.column('temperatures', _('Temperatures')), L.column('fcr', _('Expected FCR'), numeric=True),
                    L.column('in_force', _('In force today'), numeric=True)],
        'notices': [L.notice('how', 'neutral', WORDS['a_protocol_gives_per_weight_band'])],
        'rows': rows,
    }


def assignment_filters(view, context):
    filters = []
    if len(context['sites']) > 1:
        filters.append(L.choice('site', _('Site'), context['chosen_site'],
                                [('', _('All sites')), *((site.pk, site.name) for site in context['sites'])]))
    return filters + [
        L.choice('unit', _('Unit'), context['chosen_unit'],
                 [('', _('All units')), *((unit.pk, unit.code) for unit in context['units'])]),
        L.choice('batch', _('Batch'), context['chosen_batch'],
                 [('', _('All batches')), *((batch.pk, batch.code) for batch in context['batches'])]),
        L.choice('protocol', _('Protocol'), context['chosen_protocol'],
                 [('', _('All protocols')), *((each.pk, each.name) for each in context['protocol_list'])]),
        L.choice('period', _('When'), context['chosen_period'], [('', _('Any time')), *context['periods']]),
    ]


def assignments(view, objects, context):
    """Assignments: which protocol feeds which fish from which day, and the fish each row feeds now (after the more
    specific rows); the rows one dialog wrote stay next to each other (the view's order)."""
    today, request, resource = context['today'], view.request, view.resource

    def unit_cell(row):
        if not row.unit:
            return L.cell(_('wherever it is'))
        department = row.unit.production_department
        return L.cell(row.unit.code, chips=[L.chip('neutral', _('Deleted'))] if row.unit.is_deleted else (),
                      sub=[department.name + (f' · {department.site.name}' if department.site else '')])

    def batch_cell(row):
        if not row.batch:
            return L.cell(_('whatever is in it'))
        return L.cell(row.batch.code, chips=[L.chip('neutral', _('Voided'))] if row.batch.is_deleted else (),
                      sub=[row.batch.species.common_name])

    def until(row):
        said = [_('ended')] if row.valid_until and row.valid_until < today else (
            [_('starts later')] if row.valid_from > today else [])
        return L.cell(formats.date_format(row.valid_until, 'DATE_FORMAT') if row.valid_until else _('open'), sub=said)

    def actions(row):
        # the classic row's bare Edit and Delete (not "Edit <name>": a row is not named)
        done = []
        if context.get('can_change') and resource.allowed(request, row, 'change'):
            done.append(L.link(view.url('edit', row.pk), _('Edit'), 'pencil'))
        if context.get('can_delete') and resource.allowed(request, row, 'delete'):
            done.append(L.link(view.url('delete', row.pk), _('Delete'), 'trash', danger=True))
        return done

    rows = []
    for row in objects:
        protocol = row.protocol
        fed = context['feeds_now'].get(row.pk)
        rows.append(L.row(row.pk, {
            'protocol': L.title(view, context, row, protocol.name, sub=[protocol.species.common_name + (
                f' · {protocol.get_status_display()}' if protocol.status != 'active' else '')]),
            'scope': L.cell(row.scope.label),
            'unit': unit_cell(row), 'batch': batch_cell(row),
            'from': L.cell(formats.date_format(row.valid_from, 'DATE_FORMAT')),
            'until': until(row),
            'fish': L.cell(fish(fed) if fed else _('no fish')),
        }, actions(row)))
    return {
        'columns': [L.column('protocol', _('Protocol')), L.column('scope', _('Applies to')), L.column('unit', _('Unit')),
                    L.column('batch', _('Batch')), L.column('from', _('From')), L.column('until', _('Until')),
                    L.column('fish', _('Feeds now'), numeric=True)],
        'notices': [L.notice('how', 'neutral', _(
            'A protocol is assigned to units (it feeds whatever is in them), to a whole batch (it follows the batch into '
            'every unit it is moved to) or to a batch in chosen units. For a batch in a unit the most specific row in '
            'force applies: batch in unit, then unit, then whole batch. A row may be changed or deleted before its first '
            'day; afterwards it is ended by its last day.'))],
        'rows': rows,
    }
