"""Operations › Feeding › Protocols and Assignments, two tabs of core.crud. A protocol's feeding table is a grid on
its own inner tab, saved as a whole (ProtocolTableView, farm/feeding/protocols.py); Duplicate copies a protocol
into a draft. The assignment dialog writes a row per unit chosen (AssignmentCreateView)."""
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count, Prefetch, Q, Sum
from django.urls import path, reverse
from django.utils.translation import gettext as _, gettext_lazy, ngettext

from core.crud import DRAFT, CreateView, Resource, ResourceView, UpdateView, done, filter_by

from ..feeding import assignments, protocols
from ..feeding.ration import Policy, band_range
from ..feeding.read import tables
from ..forms.feeding_protocol import (
    AssignmentForm, NewAssignmentForm, ProtocolForm, column_name, table_forms,
)
from ..models import (
    Batch, FeedingProtocol, ProtocolAssignment, ProtocolBand, Site, Species, StockMovement, Tank,
)
from ..models.feeding_protocol import ProtocolStatus
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
        return {'table_form': form, 'bands': rows, 'frozen': obj.is_assigned(),
                'table_url': reverse('farm:feedingprotocol_table', args=[obj.pk]),
                'duplicate_url': reverse('farm:feedingprotocol_duplicate', args=[obj.pk])
                if request.user.has_perm(cls.perm('add')) else '',
                'table_notices': table_notices(obj)}

    @classmethod
    def urls(cls):
        p = cls.url_prefix
        return [*super().urls(),
                path(f'{p}/<uuid:pk>/table/', ProtocolTableView.as_view(resource=cls), name='feedingprotocol_table'),
                path(f'{p}/<uuid:pk>/duplicate/', DuplicateView.as_view(resource=cls),
                     name='feedingprotocol_duplicate')]


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
    present = (StockMovement.objects.filter(operation__is_deleted=False).values('unit_id', 'batch_id')
               .annotate(fish=Sum('count_delta')).filter(fish__gt=0).values_list('unit_id', 'batch_id', 'fish'))
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
