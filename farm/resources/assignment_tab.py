"""The assignment tabs of Operations › Feeding: Protocol assignments and Profile assignments (owner decision 16: the
same targets, the same rules, one page format). Each is a Resource of core.crud with `AssignmentTab` mixed in: its
model (farm.models.assignment.TargetedAssignment), the table it assigns and that table's words (`kind`). The list, the
dialog that writes a row per unit chosen, the rows' write path (farm/feeding/assignments.py) and the count of the fish
each row applies to today (the one resolver, farm/feeding/resolve.py) are written once, here."""
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.urls import reverse
from django.utils.translation import gettext as _, ngettext

from core.crud import CreateView, done, filter_by

from ..feeding import assignments
from ..feeding.resolve import Resolver
from ..models import Batch, Site, Tank
from ..stock import read as stock_read
from ..stock.dates import local_today

IN_FORCE, ENDED, PLANNED = 'now', 'ended', 'planned'


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
            form.add_error(None, str(r.kind()['meanwhile']))
            return self.page(form)
        messages_of(request, form)
        return done(request, reverse(r.url_name('list')))


def messages_of(request, form):
    from django.contrib import messages
    messages.success(request, ngettext('%(count)d assignment created.', '%(count)d assignments created.',
                                       len(form.rows)) % {'count': len(form.rows)})
    for notice in form.notices():
        messages.warning(request, notice)


class AssignmentTab:
    """What an assignment tab adds to core.crud.Resource. A subclass sets `model`, `subject_model` (the table assigned),
    the forms (`new_form`, `form_class`) and `kind_words` (its table's words: label, all, how, now, search, empty,
    meanwhile)."""

    subject_model = None
    new_form = None
    kind_words = {}
    icon = 'link'
    create_view = AssignmentCreateView
    page_size = 50
    list_template = 'farm/assignment_list.html'

    @classmethod
    def kind(cls):
        return {**cls.kind_words, 'subject': cls.model.SUBJECT}

    @classmethod
    def form(cls, request, *args, **kwargs):
        return (cls.form_class if 'instance' in kwargs else cls.new_form)(*args, **kwargs)

    @classmethod
    def queryset(cls):
        subject = cls.model.SUBJECT
        return (super().queryset().select_related(f'{subject}__species', 'unit__production_department__site',
                                                  'batch__species')
                .order_by('-valid_from', 'group_id', 'unit__code'))

    @classmethod
    def filter_list(cls, request, objects):
        today, subject = local_today(), cls.model.SUBJECT
        live = cls.model.objects.filter(is_deleted=False)      # those the person may see (core.sealing)
        sites = Site.objects.filter(pk__in=live.values('unit__production_department__site'))
        objects, chosen_site = filter_by(request, objects, 'site', sites, 'unit__production_department__site')
        units = Tank.all_objects.filter(pk__in=live.values('unit')).order_by('code')
        objects, chosen_unit = filter_by(request, objects, 'unit', units, 'unit_id')
        batches = Batch.all_objects.filter(pk__in=live.values('batch')).order_by('-code')
        objects, chosen_batch = filter_by(request, objects, 'batch', batches, 'batch_id')
        subject_list = cls.subject_model.objects.filter(assignments__is_deleted=False).distinct().order_by('name')
        objects, chosen_subject = filter_by(request, objects, subject, subject_list, f'{subject}_id')
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
                         'batches': batches, 'chosen_batch': chosen_batch, 'subject_list': subject_list,
                         'chosen_subject': chosen_subject, 'periods': periods, 'chosen_period': chosen_period,
                         'today': today, 'feeds_now': applies_now(cls.model, cls.subject_model, today),
                         'kind': cls.kind(), 'edit_name': cls.url_name('edit'), 'delete_name': cls.url_name('delete')}


def applies_now(model, subject_model, today):
    """{assignment id: fish it applies to today}: for every batch in a unit now, the row of `model` that applies to it
    (batch in unit, then unit, then whole batch: the one resolver), so a row read past for a more specific one counts
    no fish."""
    present = stock_read.present('unit_id', 'batch_id').values_list('unit_id', 'batch_id', 'fish')
    rows = list(model.objects.filter(valid_from__lte=today).filter(Q(valid_until__isnull=True)
                                                                   | Q(valid_until__gte=today)))
    species_of = dict(subject_model.all_objects.filter(pk__in={row.subject_id for row in rows})
                      .values_list('pk', 'species_id'))
    resolver = Resolver(rows, model.SUBJECT, species_of, dict(Batch.all_objects.values_list('pk', 'species_id')))
    fed = {}
    for unit_id, batch_id, fish in present:
        row, _skipped = resolver.resolve(unit_id, batch_id, today)
        if row is not None:
            fed[row.pk] = fed.get(row.pk, 0) + fish
    return fed
