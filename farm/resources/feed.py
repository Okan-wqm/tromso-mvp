from django.utils.translation import gettext, gettext_lazy as _, ngettext_lazy

from core.crud import Resource, RowList, filter_by

from ..forms import FeedForm, FeedSuitabilityFormSet
from ..models import Feed, FeedingRecord, Species, Supplier
from .withdrawal_input import WithdrawalInput


def grams(value):
    """A weight as the activity log writes it: 50, 0.5, 1500 (no trailing zeros)."""
    return format(value.normalize(), 'f')


class FeedSuitabilityList(RowList):
    """The species, life stages and fish weights a feed suits, saved as a whole list on its Suitable for
    tab, like a feeder's calibrations."""

    key, tab, label = 'suitability', 'suitability', _('Suitable for')
    formset = FeedSuitabilityFormSet
    saved = ngettext_lazy('%(count)d row saved.', '%(count)d rows saved.', 'count')

    @classmethod
    def describe(cls, row):
        """e.g. "Atlantic salmon (SAL): Smolt, 50–150 g (in fresh water)", in English."""
        lower, upper = row.min_weight_g, row.max_weight_g
        if lower is not None and upper is not None:
            band = f'{grams(lower)}–{grams(upper)} g'
        elif lower is not None:
            band = gettext('from %(weight)s g') % {'weight': grams(lower)}
        elif upper is not None:
            band = gettext('up to %(weight)s g') % {'weight': grams(upper)}
        else:
            band = ''
        text = ', '.join(part for part in (str(row.get_growth_stage_display()), band) if part)
        text = f'{row.species}: {text}'
        return f'{text} ({row.notes})' if row.notes else text


class FeedResource(WithdrawalInput, Resource):
    model = Feed
    form_class = FeedForm
    name, plural = _('feed'), _('feeds')
    url_prefix = 'feeds'
    search_fields = ['name', 'code', 'manufacturer__name']
    list_template = 'farm/feed_list.html'
    form_template = 'farm/feed_form.html'
    icon = 'wheat'
    row_lists = (FeedSuitabilityList,)
    page_size = 50

    @classmethod
    def reached(cls, request, feed):
        """A feed's type decides whether its feedings hold the fish (a medicated feed no in-feed treatment covers,
        withdrawal rule 6): the fish of the units it fed, from its first feeding."""
        fed = FeedingRecord.all_objects.filter(feed=feed).values_list('unit_id', 'date')
        return {unit for unit, _day in fed}, min((day for _unit, day in fed), default=None)

    @classmethod
    def queryset(cls):
        return super().queryset().select_related('manufacturer').prefetch_related('suitability__species')

    @classmethod
    def filter_list(cls, request, objects):
        objects, chosen_type = filter_by(request, objects, 'type', Feed.Type.choices, 'feed_type')
        manufacturers = Supplier.objects.filter(feeds__is_deleted=False).distinct()
        objects, chosen_manufacturer = filter_by(request, objects, 'manufacturer', manufacturers, 'manufacturer_id')
        species = Species.objects.filter(feed_suitability__feed__is_deleted=False).distinct()
        objects, chosen_species = filter_by(request, objects, 'species', species, 'suitability__species')
        if chosen_species:
            objects = objects.distinct()    # a feed suits a species at several stages
        objects, chosen_status = filter_by(request, objects, 'status', Feed.Status.choices, 'status')
        return objects, {
            'types': Feed.Type.choices, 'chosen_type': chosen_type,
            'manufacturers': manufacturers, 'chosen_manufacturer': chosen_manufacturer,
            'species_list': species, 'chosen_species': chosen_species,
            'statuses': Feed.Status.choices, 'chosen_status': chosen_status,
        }
