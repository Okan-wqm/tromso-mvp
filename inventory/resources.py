"""Company › Facility › Storage locations: the store's one tab on top of core.crud, with its reorder levels
saved as a list on a tab of their own."""
from django.utils.translation import gettext_lazy as _, ngettext, ngettext_lazy

from core import formpanels, listprops as L
from core.crud import Resource, RowList, filter_by
from farm.models import Site

from . import read, services
from .forms import ReorderLevelFormSet, StorageLocationForm
from .models import StorageLocation, Unit


class ReorderLevels(RowList):
    """A location's reorder levels, one per feed (owner decision Q-S4), saved as a whole list. A row
    chooses a feed and stores the feed's item of the store, made when the feed has none yet."""

    key, tab, label = 'reorder', 'reorder', _('Reorder levels')
    # Its panel's words (inventory/location_form.html).
    title = _('Reorder levels')
    help_text = _('Below the reorder level of a feed in this location, the Storage overview says the stock is low. One row '
                  'per feed. They are saved separately from the location details.')
    empty_text = _('No reorder levels yet. Use “Add feed” to add a row.')
    add_label, save_label = _('Add feed'), _('Save reorder levels')
    pending_text = _('Reorder levels can be set once the location is created.')
    formset = ReorderLevelFormSet
    saved = ngettext_lazy('%(count)d reorder level saved.', '%(count)d reorder levels saved.', 'count')

    @classmethod
    def values(cls, user, row, fields):
        return {'item': services.item_for(row['feed'], user), 'level': row['level']}

    @classmethod
    def describe(cls, row):
        """e.g. "Nutra 3 mm (N3): 2000 kg", in English."""
        return f'{row.item}: {row.level.normalize():f} {row.item.unit}'


class StorageLocationResource(Resource):
    model = StorageLocation
    form_class = StorageLocationForm
    name, plural = _('storage location'), _('storage locations')
    url_prefix = 'storage-locations'
    search_fields = ['name', 'code']
    list_template = 'inventory/location_list.html'
    form_template = 'inventory/location_form.html'
    icon = 'warehouse'
    row_lists = (ReorderLevels,)
    page_size = 50

    @classmethod
    def next_panels(cls, view, form, obj, extra):
        """inventory/location_form.html in the new look: its row lists."""
        return formpanels.row_list_panels(cls, view, obj, extra)

    @classmethod
    def queryset(cls):
        return super().queryset().select_related('site', 'feeder').order_by('site__name', 'code')

    @classmethod
    def filter_list(cls, request, objects):
        sites = Site.objects.filter(storage_locations__is_deleted=False).distinct().order_by('name')
        objects, chosen_site = filter_by(request, objects, 'site', sites, 'site_id')
        objects, chosen_kind = filter_by(request, objects, 'kind', StorageLocation.Kind.choices, 'kind')
        objects, chosen_status = filter_by(request, objects, 'status', StorageLocation.Status.choices, 'status')
        held = {}     # location id -> (kg on hand, lots with stock): kilos only, never added to things counted
        for row in read.buckets():
            kilos, lots = held.get(row.location.pk, (0, 0))
            held[row.location.pk] = (kilos + (row.quantity if row.item.unit == Unit.KG else 0), lots + 1)
        return objects, {
            'sites': sites, 'chosen_site': chosen_site, 'kinds': StorageLocation.Kind.choices,
            'chosen_kind': chosen_kind, 'statuses': StorageLocation.Status.choices, 'chosen_status': chosen_status,
            'held': held,
        }

    # The list in the new look (core/listprops.py), in the classic list's words (inventory/location_list.html).
    search_placeholder = _('Search by name or code')
    empty_text = _('A storage location is a place on a site where stock is kept: a feed store, a silo, a cold room, a '
                   'medicine cabinet.')

    @classmethod
    def list_filters(cls, view, context):
        return [
            L.choice('site', _('Site'), context['chosen_site'],
                     [('', _('All sites')), *((site.pk, site.name) for site in context['sites'])]),
            L.choice('kind', _('Kind'), context['chosen_kind'], [('', _('All kinds')), *context['kinds']]),
            L.choice('status', _('Status'), context['chosen_status'], [('', _('All statuses')), *context['statuses']]),
        ]

    @classmethod
    def list_rows(cls, view, objects, context):
        from .templatetags.inventory import quantity

        def on_hand(location):
            held = context['held'].get(location.pk)
            if not held:
                return L.cell('—')
            kilos, lots = held
            return L.cell(quantity(kilos), sub=[ngettext('%(lots)s lot', '%(lots)s lots', lots) % {'lots': lots}])

        return {
            'columns': [L.column('location', _('Location')), L.column('site', _('Site')), L.column('kind', _('Kind')),
                        L.column('feeder', _('Feeder')), L.column('capacity', _('Capacity'), numeric=True),
                        L.column('held', _('On hand now'), numeric=True), L.column('status', _('Status'))],
            'rows': [L.row(location.pk, {
                'location': L.title(view, context, location, location.name, sub=[location.code]),
                'site': L.cell(location.site.name),
                'kind': L.cell(location.get_kind_display()),
                'feeder': L.cell(location.feeder.name if location.feeder else '—'),
                'capacity': L.cell(quantity(location.capacity, location.get_capacity_unit_display())
                                   if location.capacity is not None else '—'),
                'held': on_hand(location),
                'status': L.badge(location.status, location.get_status_display()),
            }, L.edit_delete(view, context, location, location.name)) for location in objects],
        }
