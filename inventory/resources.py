"""Company › Facility › Storage locations: the store's one tab on top of core.crud, with its reorder levels
saved as a list on a tab of their own."""
from django.utils.translation import gettext_lazy as _, ngettext_lazy

from core.crud import Resource, RowList, filter_by
from farm.models import Site

from . import read, services
from .forms import ReorderLevelFormSet, StorageLocationForm
from .models import StorageLocation, Unit


class ReorderLevels(RowList):
    """A location's reorder levels, one per feed (owner decision Q-S4), saved as a whole list. A row
    chooses a feed and stores the feed's item of the store, made when the feed has none yet."""

    key, tab, label = 'reorder', 'reorder', _('Reorder levels')
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
