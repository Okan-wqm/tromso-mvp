from django.utils.translation import gettext, gettext_lazy as _, ngettext_lazy

from core import formpanels, listprops as L
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
    # Its panel's words (farm/feed_form.html).
    title = _('Suitable for')
    help_text = _('The species and life stages it is made for, and the fish weights in grams: from the lower weight up to, '
                  'not including, the upper one; leave an end empty when it has none. One row per species and stage, at '
                  'most 50. They are saved separately from the feed details.')
    empty_text = _('No species yet. Use “Add species” to add a row.')
    add_label, save_label = _('Add species'), _('Save suitability')
    pending_text = _('Species and fish weights can be added once the feed is created.')
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
    def next_panels(cls, view, form, obj, extra):
        """farm/feed_form.html in the new look: its row lists."""
        return formpanels.row_list_panels(cls, view, obj, extra)

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

    # The list in the new look (core/listprops.py), in the classic list's words (farm/feed_list.html).
    search_placeholder = _('Search by name, code or manufacturer')
    empty_text = _('The feeds the farm uses: who makes them, their pellet and analysis, and the species and fish weights each '
                   'one suits.')

    @classmethod
    def list_filters(cls, view, context):
        return [
            L.choice('type', _('Feed type'), context['chosen_type'], [('', _('All feed types')), *context['types']]),
            L.choice('manufacturer', _('Manufacturer'), context['chosen_manufacturer'],
                     [('', _('All manufacturers')), *((each.pk, each.name) for each in context['manufacturers'])]),
            L.choice('species', _('Suitable for'), context['chosen_species'],
                     [('', _('All species')), *((each.pk, each.common_name) for each in context['species_list'])]),
            L.choice('status', _('Status'), context['chosen_status'], [('', _('All statuses')), *context['statuses']]),
        ]

    @classmethod
    def list_rows(cls, view, objects, context):
        from django.template.defaultfilters import floatformat

        def figure(value):
            return floatformat(value, '-2')

        def band(row):
            """farm/_weight_band.html: ", 50–150 g", ", from 50 g", ", up to 150 g", or nothing."""
            lower, upper = row.min_weight_g, row.max_weight_g
            if lower is not None and upper is not None:
                return f', {figure(lower)}–{figure(upper)} g'
            if lower is not None:
                return ', ' + _('from %(weight)s g') % {'weight': figure(lower)}
            if upper is not None:
                return ', ' + _('up to %(weight)s g') % {'weight': figure(upper)}
            return ''

        def manufacturer(feed):
            if feed.manufacturer is None:
                return L.cell('–')
            maker = feed.manufacturer
            return L.cell(maker.name, sub=[maker.get_status_display() if maker.status != 'active' else ''])

        def analysis(feed):
            if feed.protein_pct is None and feed.fat_pct is None:
                return '–'
            return f"{figure(feed.protein_pct) or '–'} / {figure(feed.fat_pct) or '–'} %"

        def energy(feed):
            gross = f'{figure(feed.gross_energy_mj_kg)} MJ/kg' if feed.gross_energy_mj_kg is not None else '–'
            digestible = _('%(energy)s MJ/kg digestible') % {'energy': figure(feed.digestible_energy_mj_kg)} \
                if feed.digestible_energy_mj_kg is not None else ''
            return L.cell(gross, sub=[digestible])

        def suits(feed):
            lines = [f'{row.species.common_name} · {row.get_growth_stage_display()}{band(row)}'
                     for row in feed.suitability.all()]
            return L.cell('; '.join(lines) if lines else '–')

        return {
            'columns': [L.column('feed', _('Feed')), L.column('manufacturer', _('Manufacturer')),
                        L.column('type', _('Feed type')), L.column('pellet', _('Pellet')),
                        L.column('analysis', _('Protein / fat')), L.column('energy', _('Energy')),
                        L.column('suits', _('Suitable for')), L.column('price', _('Price per kg')),
                        L.column('status', _('Status'))],
            'rows': [L.row(feed.pk, {
                'feed': L.title(view, context, feed, feed.name, sub=[feed.code]),
                'manufacturer': manufacturer(feed),
                'type': L.cell(feed.get_feed_type_display()),
                'pellet': L.cell(f'{figure(feed.pellet_size_mm)} mm' if feed.pellet_size_mm is not None else '–',
                                 sub=[feed.get_buoyancy_display() if feed.buoyancy else '']),
                'analysis': L.cell(analysis(feed)),
                'energy': energy(feed),
                'suits': suits(feed),
                'price': L.cell(f"{floatformat(feed.price_per_kg, '2g')} {feed.currency}" if feed.price_per_kg is not None
                                else '–'),
                'status': L.badge(feed.status, feed.get_status_display()),
            }, L.edit_delete(view, context, feed, feed.name)) for feed in objects],
        }
