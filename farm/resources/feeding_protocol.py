"""Operations › Feeding › Protocols and Assignments, two tabs of core.crud. A protocol's feeding table is a grid on
its own inner tab, saved as a whole (ProtocolTableView, farm/feeding/protocols.py); Duplicate copies a protocol
into a draft. The assignment dialog writes a row per unit chosen (AssignmentCreateView)."""
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count, Prefetch, Q
from django.urls import path, reverse
from django.utils.translation import gettext as _, gettext_lazy, ngettext

from core import formpanels, listprops
from core.crud import DRAFT, CreateView, Resource, ResourceView, UpdateView, done, filter_by

from .. import words
from ..feeding import assignments, lists, protocols
from ..feeding.growth import economic_fcr
from ..feeding.ration import Policy, band_range
from ..feeding.read import tables
from ..forms.feeding_protocol import (
    AssignmentForm, NewAssignmentForm, ProtocolForm, column_name, table_forms,
)
from ..models import (
    Batch, FeedingProtocol, ProtocolAssignment, ProtocolBand, Site, Species, Tank,
)
from ..models.feeding_protocol import ProtocolStatus
from ..stock import read as stock_read
from ..stock.dates import local_today


class FeedingProtocolResource(Resource):
    model = FeedingProtocol
    form_class = ProtocolForm
    name, plural = gettext_lazy('feeding protocol'), gettext_lazy('feeding protocols')
    url_prefix = 'operations/feeding/protocols'
    search_fields = ['name', 'species__common_name', 'species__local_name', 'notes']
    list_template = 'farm/feeding_protocol_list.html'
    form_template = 'farm/feeding_protocol_form.html'
    icon = 'table'
    page_size = 50
    # the new look's list (farm/feeding/lists.py) in the classic list's words (farm/feeding_protocol_list.html)
    search_placeholder = gettext_lazy('Search by name, species or notes')
    empty_text = gettext_lazy('The feeding tables the farm feeds by: per weight band and water temperature, the feed and '
                              'the share of the body weight given a day.')
    list_rows = staticmethod(lists.protocols)
    list_filters = staticmethod(lists.protocol_filters)

    @classmethod
    def queryset(cls):
        bands = ProtocolBand.objects.select_related('feed').prefetch_related('rates').order_by('min_weight_g')
        return super().queryset().select_related('species').prefetch_related(Prefetch('bands', bands))

    @classmethod
    def filter_list(cls, request, objects):
        today = local_today()
        objects = objects.annotate(in_force=Count('assignments', filter=Q(
            assignments__is_deleted=False, assignments__valid_from__lte=today)
            & (Q(assignments__valid_until__isnull=True) | Q(assignments__valid_until__gte=today))))
        species = Species.objects.filter(feeding_protocols__is_deleted=False).distinct().order_by('common_name')
        objects, chosen_species = filter_by(request, objects, 'species', species, 'species_id')
        objects, chosen_status = filter_by(request, objects, 'status', ProtocolStatus.choices, 'status')
        return objects, {'species_list': species, 'chosen_species': chosen_species,
                         'statuses': ProtocolStatus.choices, 'chosen_status': chosen_status}

    @classmethod
    def edit_extras(cls, request, obj, draft=None, data=None):
        """The feeding table tab: the grid (to edit while the protocol is not assigned) or the table as it is."""
        form, rows = table_forms(obj, data=data, draft=draft)
        return {'table_form': form, 'bands': rows, 'frozen': obj.is_assigned(), 'band_terms': band_terms(obj),
                'used': used_props(obj),
                'table_url': reverse('farm:feedingprotocol_table', args=[obj.pk]),
                'duplicate_url': reverse('farm:feedingprotocol_duplicate', args=[obj.pk])
                if request.user.has_perm(cls.perm('add')) else '',
                'table_notices': table_notices(obj)}

    next_extras = frozenset({'table_form', 'bands', 'frozen', 'band_terms', 'used', 'table_url', 'duplicate_url', 'table_notices'})

    @classmethod
    def next_panels(cls, view, form, protocol, extra):
        """farm/feeding_protocol_form.html in the new look: the Feeding table tab, the grid of weight bands by temperature
        columns saved as a whole (the columns typed render the grid again: a draft), or, once the protocol is assigned,
        the table as it is; the notices of its bands, and Duplicate."""
        from ..templatetags.feeding import celsius, fcr, weights
        from ..templatetags.stock import percent
        title = words.FEEDING_TABLE
        if protocol is None:
            return [formpanels.panel('table', title, [
                formpanels.help_text(words.THE_FEEDING_TABLE_CAN_BE_FILLED)])]
        table_form, bands = extra['table_form'], extra['bands']
        if extra.get('frozen'):
            columns = protocol.columns()
            blocks = [formpanels.notice(words.THE_PROTOCOL_IS_ASSIGNED_SO_ITS),
                formpanels.table(title, [
                    listprops.column('band', words.WEIGHT_BAND), listprops.column('feed', words.FEED),
                    listprops.column('meals', words.MEALS_A_DAY, numeric=True),
                    listprops.column('fcr', words.EXPECTED_FCR, numeric=True),
                    listprops.column('uneaten', words.UNEATEN_FEED, numeric=True),
                    listprops.column('economic', words.ECONOMIC_FCR, numeric=True),
                    listprops.column('mortality', words.MORTALITY_A_MONTH, numeric=True),
                    *(listprops.column(f't{index}', celsius(temperature), numeric=True)
                      for index, temperature in enumerate(columns))], [
                    listprops.row(band.id, {
                        'band': listprops.cell(weights(band)), 'feed': listprops.cell(band.feed),
                        'meals': listprops.cell(band.meals),
                        'fcr': listprops.cell(fcr(terms['fcr'])),
                        'uneaten': listprops.cell(percent(terms['uneaten_pct'], 1)),
                        'economic': listprops.cell(fcr(terms['economic_fcr'])),
                        'mortality': listprops.cell(percent(terms['mortality_pct_month'], 2)),
                        **{f't{index}': listprops.cell(percent(cell.sfr_pct, 2))
                           for index, cell in enumerate(band.cells)}})
                    for terms in extra['band_terms'] for band in [terms['band']]]), formpanels.help_text(words.BETWEEN_TWO_BANDS_THE_FCR)]
        else:
            columns = list(bands.columns)
            cells = {column_name(temperature) for temperature in columns}
            blocks = [formpanels.help_text(words.ONE_ROW_PER_WEIGHT_BAND_FROM),
                formpanels.form(extra['table_url'], title, [
                    formpanels.fields(table_form['temperatures']),
                    formpanels.grid(
                        bands, [words.FROM_G, words.UP_TO_G, words.FEED, words.MEALS_A_DAY, words.EXPECTED_FCR,
                                words.UNEATEN_FEED, words.MORTALITY_A_MONTH,
                                *(words.sfr_at(celsius(each)) for each in columns)],
                        lambda row: [[bound] for bound in row.base_fields_shown] + [[bound] for bound in row.cells]
                        + [[row['DELETE']]],
                        legend=title, add=words.ADD_BAND, can_add=bool(columns),
                        empty_text=words.NO_BAND_YET_USE_ADD_BAND if columns
                        else words.GIVE_THE_TEMPERATURE_COLUMNS_FIRST_THE,
                        label_of=lambda bound: words.sfr_at(bound.label)
                        if bound.name in cells else bound.label)],
                    hidden=[table_form['version']],
                    errors=[*table_form.non_field_errors(), *bands.non_form_errors()],
                    actions=[formpanels.button(words.SAVE_TABLE, primary=True)])]
        used = extra.get('used')
        if used:
            blocks += [formpanels.table(used['title'], used['columns'], used['rows']),
                       *(formpanels.help_text(line) for line in used['lines'])]
        blocks += [formpanels.notice(text, 'warning') for text in extra.get('table_notices', ())]
        if extra.get('duplicate_url'):
            blocks += [formpanels.post(extra['duplicate_url'], words.DUPLICATE),
                       formpanels.help_text(words.A_DRAFT_COPY_WITH_THIS_TABLE)]
        refused = bands.is_bound and (bool(bands.non_form_errors()) or any(bands.errors)) or bool(table_form.errors)
        return [formpanels.panel('table', title, blocks, has_errors=refused)]

    @classmethod
    def urls(cls):
        p = cls.url_prefix
        return [*super().urls(),
                path(f'{p}/<uuid:pk>/table/', ProtocolTableView.as_view(resource=cls), name='feedingprotocol_table'),
                path(f'{p}/<uuid:pk>/duplicate/', DuplicateView.as_view(resource=cls),
                     name='feedingprotocol_duplicate')]


def used_props(protocol):
    """The values a stored table actually gives over the fish's weight (ration.Table.used: the functions the ration and
    the growth read), as the columns and rows both looks draw: a row at every band's lower weight and at every band's
    anchor weight, where the values entered sit (said in the Point column); the FCR, the uneaten share and the SFR at each
    temperature column, each with its between-band rule in its heading's line. None without a stored table."""
    from ..templatetags.feeding import celsius, fcr
    from ..templatetags.stock import grams, percent
    if protocol is None or protocol.pk is None:
        return None
    table = tables([protocol.pk])[protocol.pk]
    if not table.bands:
        return None
    columns = table.columns()
    return {
        'title': str(words.VALUES_USED_OVER_THE_WEIGHT),
        'lines': [str(words.THE_VALUES_THE_TABLE_GIVES), _('FCR: %(fcr)s · uneaten feed: %(uneaten)s · SFR: %(sfr)s') % {
            'fcr': protocol.get_fcr_between_display(), 'uneaten': protocol.get_uneaten_between_display(),
            'sfr': protocol.get_sfr_between_display()}],
        'columns': [listprops.column('weight', words.FISH_WEIGHT, numeric=True),
                    listprops.column('point', words.POINT),
                    listprops.column('band', words.WEIGHT_BAND),
                    listprops.column('fcr', words.EXPECTED_FCR, numeric=True),
                    listprops.column('uneaten', words.UNEATEN_FEED, numeric=True),
                    *(listprops.column(f't{index}', words.sfr_at(celsius(temperature)), numeric=True)
                      for index, temperature in enumerate(columns))],
        'rows': [listprops.row(f'used-{index}', {
            'weight': listprops.cell(grams(used.weight_g), strong=used.anchor),
            'point': listprops.cell(words.ENTERED_FOR_THE_BAND if used.anchor else words.THE_BANDS_LOWER_WEIGHT),
            'band': listprops.cell(band_range(used.band.min_weight_g, used.band.max_weight_g)),
            'fcr': listprops.cell(fcr(used.fcr)), 'uneaten': listprops.cell(percent(used.uneaten_pct, 1)),
            **{f't{at}': listprops.cell(percent(value, 3)) for at, value in enumerate(used.sfr)}})
            for index, used in enumerate(table.used())],
    }


def band_terms(protocol):
    """A stored protocol's bands as the ration reads them (ration.Table), each with the values in force in it: its
    expected FCR, uneaten share and expected mortality (its own, else the protocol's) and the economic FCR they give.
    What the fixed table of an assigned protocol shows, in both looks."""
    if protocol is None or protocol.pk is None:
        return []
    table = tables([protocol.pk])[protocol.pk]
    return [{'band': band, 'fcr': table.fcr_of(band), 'fcr_own': band.fcr is not None,
             'uneaten_pct': table.uneaten_of(band),
             'economic_fcr': economic_fcr(table.fcr_of(band), table.uneaten_of(band)),
             'mortality_pct_month': table.mortality_of(band)} for band in table.bands]


def table_notices(protocol):
    """Bands whose feed is not listed as suitable for the protocol's species at the band's weights (a notice, not a
    refusal, as the feeding dialog does)."""
    notices = []
    for band in protocol.bands.select_related('feed').prefetch_related('feed__suitability'):
        rows = [row for row in band.feed.suitability.all() if row.species_id == protocol.species_id]
        lower, upper = band.min_weight_g, band.max_weight_g
        fits = any((row.min_weight_g is None or row.min_weight_g <= lower)
                   and (row.max_weight_g is None or upper is not None and upper <= row.max_weight_g) for row in rows)
        if not fits:
            notices.append(_('%(feed)s is not listed as suitable for %(species)s at %(range)s (Reference data › '
                             'Feeds).') % {'feed': band.feed, 'species': protocol.species,
                                           'range': band_range(lower, upper)})
    return notices


class ProtocolTableView(ResourceView):
    """Saves a protocol's feeding table, a part of editing the protocol (its change permission). Posted with the
    draft marker, it renders the grid again with the columns changed and what was entered."""

    action = 'change'

    def get(self, request, pk):
        return done(request, reverse(self.resource.url_name('edit'), args=[pk]))

    def post(self, request, pk):
        r = self.resource
        obj = self.get_object(pk)
        page = UpdateView.as_page(r, request)
        if DRAFT in request.POST:
            return page.page(r.form(request, instance=obj), obj, open_tab='table',
                             **r.edit_extras(request, obj, draft=request.POST))
        form, rows = table_forms(obj, data=request.POST)
        if form.is_valid() & rows.is_valid():
            try:
                protocols.save_table(request.user, obj, form.cleaned_data['temperatures'], rows.kept(),
                                     form.cleaned_data['version'], column_name)
            except ValidationError as error:
                form.add_error(None, error.messages)
            else:
                messages.success(request, _('Feeding table of “%(protocol)s” saved.') % {'protocol': obj})
                for notice in table_notices(obj):
                    messages.warning(request, notice)
                return done(request, reverse(r.url_name('edit'), args=[pk]), stay=True)
        response = page.page(r.form(request, instance=obj), obj, open_tab='table',
                             **{**r.edit_extras(request, obj), 'table_form': form, 'bands': rows})
        response.status_code = 422
        return response


class DuplicateView(ResourceView):
    """A draft copy of a protocol and its table (the add permission), opened for editing."""

    action = 'add'

    def get(self, request, pk):
        return done(request, reverse(self.resource.url_name('edit'), args=[pk]))

    def post(self, request, pk):
        r = self.resource
        copy = protocols.duplicate(request.user, self.get_object(pk), r.snapshot)
        messages.success(request, _('Copied as “%(protocol)s”, a draft: change it, set it active and assign it.') % {
            'protocol': copy})
        return done(request, reverse(r.url_name('edit'), args=[copy.pk]), stay=True)


# ---- assignments ----------------------------------------------------------------------------------------
class AssignmentCreateView(CreateView):
    """The assignment dialog: a row per unit chosen (or one for a whole batch), written together, each logged."""

    def post(self, request):
        r = self.resource
        form = r.form(request, request.POST)
        if form.sent_before() is not None:                 # the same dialog sent again (core.models.EntryKey)
            return done(request, reverse(r.url_name('list')))
        if not form.is_valid():
            return self.page(form)
        try:
            with transaction.atomic():
                form.note_sent(assignments.save(request.user, form.rows)[0])
        except ValidationError as error:                   # its key stands for another record (EntryKey.note)
            form.add_error(None, error.messages)
            return self.page(form)
        except IntegrityError:
            if form.sent_before() is not None:             # sent twice at once: the other sending wrote them
                return done(request, reverse(r.url_name('list')))
            form.add_error(None, _('Another protocol was assigned to these fish meanwhile: look at the list and try '
                                   'again.'))
            return self.page(form)
        messages.success(request, ngettext('%(count)d assignment created.', '%(count)d assignments created.',
                                           len(form.rows)) % {'count': len(form.rows)})
        for notice in form.notices():
            messages.warning(request, notice)
        return done(request, reverse(r.url_name('list')))


IN_FORCE, ENDED, PLANNED = 'now', 'ended', 'planned'


class ProtocolAssignmentResource(Resource):
    model = ProtocolAssignment
    form_class = AssignmentForm
    name, plural = gettext_lazy('protocol assignment'), gettext_lazy('protocol assignments')
    url_prefix = 'operations/feeding/assignments'
    search_fields = ['protocol__name', 'unit__code', 'batch__code', 'notes']
    list_template = 'farm/protocol_assignment_list.html'
    icon = 'link'
    create_view = AssignmentCreateView
    page_size = 50
    # the new look's list (farm/feeding/lists.py) in the classic list's words (farm/protocol_assignment_list.html)
    search_placeholder = gettext_lazy('Search by protocol, unit or batch')
    empty_text = gettext_lazy('Which feeding protocol feeds which fish, from which day.')
    list_rows = staticmethod(lists.assignments)
    list_filters = staticmethod(lists.assignment_filters)

    @classmethod
    def form(cls, request, *args, **kwargs):
        return (AssignmentForm if 'instance' in kwargs else NewAssignmentForm)(*args, **kwargs)

    @classmethod
    def queryset(cls):
        return (super().queryset().select_related('protocol__species', 'unit__production_department__site',
                                                  'batch__species')
                .order_by('-valid_from', 'group_id', 'unit__code'))

    @classmethod
    def filter_list(cls, request, objects):
        today = local_today()
        live = ProtocolAssignment.objects.filter(is_deleted=False)      # those the person may see (core.sealing)
        sites = Site.objects.filter(pk__in=live.values('unit__production_department__site'))
        objects, chosen_site = filter_by(request, objects, 'site', sites, 'unit__production_department__site')
        units = Tank.all_objects.filter(pk__in=live.values('unit')).order_by('code')
        objects, chosen_unit = filter_by(request, objects, 'unit', units, 'unit_id')
        batches = Batch.all_objects.filter(pk__in=live.values('batch')).order_by('-code')
        objects, chosen_batch = filter_by(request, objects, 'batch', batches, 'batch_id')
        protocol_list = FeedingProtocol.objects.filter(assignments__is_deleted=False).distinct().order_by('name')
        objects, chosen_protocol = filter_by(request, objects, 'protocol', protocol_list, 'protocol_id')
        periods = [(IN_FORCE, _('In force today')), (PLANNED, _('Starting later')), (ENDED, _('Ended'))]
        chosen_period = request.GET.get('period', '')
        if chosen_period == IN_FORCE:
            objects = objects.filter(Q(valid_until__isnull=True) | Q(valid_until__gte=today), valid_from__lte=today)
        elif chosen_period == PLANNED:
            objects = objects.filter(valid_from__gt=today)
        elif chosen_period == ENDED:
            objects = objects.filter(valid_until__lt=today)
        else:
            chosen_period = ''
        return objects, {'sites': sites, 'chosen_site': chosen_site, 'units': units, 'chosen_unit': chosen_unit,
                         'batches': batches, 'chosen_batch': chosen_batch, 'protocol_list': protocol_list,
                         'chosen_protocol': chosen_protocol, 'periods': periods, 'chosen_period': chosen_period,
                         'today': today, 'feeds_now': feeds_now(today)}


def feeds_now(today):
    """{assignment id: fish it feeds today}: for every batch in a unit now, the row that applies to it (batch in
    unit, then unit, then whole batch; ration.Policy), so a row read past for a more specific one feeds nothing."""
    present = stock_read.present('unit_id', 'batch_id').values_list('unit_id', 'batch_id', 'fish')
    rows = list(ProtocolAssignment.objects.filter(valid_from__lte=today)
                .filter(Q(valid_until__isnull=True) | Q(valid_until__gte=today)))
    species = dict(Batch.all_objects.values_list('pk', 'species_id'))
    policy = Policy(rows, tables({row.protocol_id for row in rows}), species, lambda unit_id, day: None)
    fed = {}
    for unit_id, batch_id, fish in present:
        row, _skipped = policy.resolve(unit_id, batch_id, today)
        if row is not None:
            fed[row.pk] = fed.get(row.pk, 0) + fish
    return fed
