"""The new look's lists (core/listprops.py, island `list-page`) of Operations › Feeding's two tabs, Protocols and
Assignments (farm/resources/feeding_protocol.py: `list_rows`, `list_filters`), worded as their classic templates word them
(templates/farm/feeding_protocol_list.html, protocol_assignment_list.html: the same msgids) from the rows and the context
the one list view (core.crud.ListView) read for the classic page."""
from django.template.defaultfilters import floatformat, truncatechars
from django.utils import formats
from django.utils.translation import gettext as _, ngettext

from core import listprops as L

from .. import words
from ..words import WORDS

from ..templatetags.feeding import celsius, fcr, weights
from ..templatetags.stock import fish

DASH = '—'
PROTOCOL_CHIP = {'active': 'ok', 'draft': 'neutral', 'retired': 'neutral'}


def protocol_filters(view, context):
    return [L.choice('species', str(words.SPECIES_SINGULAR), context['chosen_species'],
                     [('', str(words.ALL_SPECIES)), *((each.pk, each.common_name) for each in context['species_list'])]),
            L.choice('status', str(words.STATUS), context['chosen_status'], [('', str(words.ALL_STATUSES)), *context['statuses']])]


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
            'bands': L.cell(bands[0], sub=bands[1:]) if bands else L.cell(str(words.NO_TABLE_YET)),
            'temperatures': _temperatures(protocol),
            'fcr': L.cell(fcr(protocol.expected_fcr)),
            'in_force': L.cell(protocol.in_force or DASH),
        }, L.edit_delete(view, context, protocol, protocol.name)))
    return {
        'columns': [L.column('protocol', str(words.PROTOCOL)), L.column('species', str(words.SPECIES_SINGULAR)),
                    L.column('status', str(words.STATUS)), L.column('bands', str(words.WEIGHT_BANDS)),
                    L.column('temperatures', str(words.TEMPERATURES)), L.column('fcr', str(words.EXPECTED_FCR), numeric=True),
                    L.column('in_force', str(words.IN_FORCE_TODAY), numeric=True)],
        'notices': [L.notice('how', 'neutral', WORDS['a_protocol_gives_per_weight_band'])],
        'rows': rows,
    }


def assignment_filters(view, context):
    filters = []
    if len(context['sites']) > 1:
        filters.append(L.choice('site', str(words.SITE), context['chosen_site'],
                                [('', str(words.ALL_SITES)), *((site.pk, site.name) for site in context['sites'])]))
    return filters + [
        L.choice('unit', str(words.UNIT), context['chosen_unit'],
                 [('', str(words.ALL_UNITS)), *((unit.pk, unit.code) for unit in context['units'])]),
        L.choice('batch', str(words.BATCH), context['chosen_batch'],
                 [('', str(words.ALL_BATCHES)), *((batch.pk, batch.code) for batch in context['batches'])]),
        L.choice('protocol', str(words.PROTOCOL), context['chosen_protocol'],
                 [('', str(words.ALL_PROTOCOLS)), *((each.pk, each.name) for each in context['protocol_list'])]),
        L.choice('period', str(words.WHEN), context['chosen_period'], [('', str(words.ANY_TIME)), *context['periods']]),
    ]


def assignments(view, objects, context):
    """Assignments: which protocol feeds which fish from which day, and the fish each row feeds now (after the more
    specific rows); the rows one dialog wrote stay next to each other (the view's order)."""
    today, request, resource = context['today'], view.request, view.resource

    def unit_cell(row):
        if not row.unit:
            return L.cell(str(words.WHEREVER_IT_IS))
        department = row.unit.production_department
        return L.cell(row.unit.code, chips=[L.chip('neutral', str(words.DELETED))] if row.unit.is_deleted else (),
                      sub=[department.name + (f' · {department.site.name}' if department.site else '')])

    def batch_cell(row):
        if not row.batch:
            return L.cell(str(words.WHATEVER_IS_IN_IT))
        return L.cell(row.batch.code, chips=[L.chip('neutral', str(words.VOIDED))] if row.batch.is_deleted else (),
                      sub=[row.batch.species.common_name])

    def until(row):
        said = [str(words.ENDED)] if row.valid_until and row.valid_until < today else (
            [str(words.STARTS_LATER)] if row.valid_from > today else [])
        return L.cell(formats.date_format(row.valid_until, 'DATE_FORMAT') if row.valid_until else str(words.OPEN), sub=said)

    def actions(row):
        # the classic row's bare Edit and Delete (not "Edit <name>": a row is not named)
        done = []
        if context.get('can_change') and resource.allowed(request, row, 'change'):
            done.append(L.link(view.url('edit', row.pk), str(words.EDIT), 'pencil'))
        if context.get('can_delete') and resource.allowed(request, row, 'delete'):
            done.append(L.link(view.url('delete', row.pk), str(words.DELETE), 'trash', danger=True))
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
            'fish': L.cell(fish(fed) if fed else str(words.NO_FISH)),
        }, actions(row)))
    return {
        'columns': [L.column('protocol', str(words.PROTOCOL)), L.column('scope', str(words.APPLIES_TO)), L.column('unit', str(words.UNIT)),
                    L.column('batch', str(words.BATCH)), L.column('from', str(words.FROM)), L.column('until', str(words.UNTIL)),
                    L.column('fish', str(words.FEEDS_NOW), numeric=True)],
        'notices': [L.notice('how', 'neutral', str(words.A_PROTOCOL_IS_ASSIGNED_TO_UNITS_IT))],
        'rows': rows,
    }
