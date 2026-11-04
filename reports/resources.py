import uuid
from urllib.parse import urlencode

from django.db.models import Exists, OuterRef
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _, ngettext_lazy

from core import audit
from core.crud import Resource, RowList, filter_by
from farm.health.read import with_deaths
from farm.models import EscapeRecord, HealthEvent, SlaughterFacility, Site

from . import compute, due, exports, periods, services
from .forms import (
    ReportForm, ResistanceSuspicionFormSet, SensitivityTestFormSet, SubmitForm, TreatmentAnswerFormSet,
    UnitAnswerFormSet,
)
from .kinds import SCHEDULED, URGENT, ReportKind
from .models import Report

STATUSES = [('draft', _('Draft')), ('filed', _('Filed'))]


class ReportRows(RowList):
    """A list of answers of a report, edited while it is a draft (a database trigger refuses it once filed)."""
    kinds = ()
    saved = ngettext_lazy('%(count)d row saved.', '%(count)d rows saved.', 'count')

    @classmethod
    def applies_to(cls, report):
        return report.kind in cls.kinds and report.submitted_at is None


class TreatmentAnswers(ReportRows):
    key, tab, label = 'treatments', 'treatments', _('Treatments')
    formset = TreatmentAnswerFormSet
    kinds = (ReportKind.SEA_LICE,)

    @classmethod
    def describe(cls, row):
        """e.g. "Bath, 12 Nov · before the count · combination 1"."""
        parts = [str(row.treatment), audit.english(_('before the count')) if row.done_before_count
                 else audit.english(_('after the count'))]
        if row.combination:
            parts.append(f'{audit.english(_("combination"))} {row.combination}')
        return ' · '.join(parts)


class ResistanceSuspicions(ReportRows):
    key, tab, label = 'resistance', 'resistance', _('Resistance suspicions')
    formset = ResistanceSuspicionFormSet
    kinds = (ReportKind.SEA_LICE,)

    @classmethod
    def describe(cls, row):
        """e.g. "Azamethiphos · A bioassay", the other substance or reason in brackets."""
        substance = row.get_substance_display() + (f' ({row.other_substance})' if row.other_substance else '')
        cause = row.get_cause_display() + (f' ({row.other_cause})' if row.other_cause else '')
        return f'{substance} · {cause}'


class SensitivityTests(ReportRows):
    key, tab, label = 'sensitivity', 'sensitivity', _('Sensitivity tests')
    formset = SensitivityTestFormSet
    kinds = (ReportKind.SEA_LICE,)

    @classmethod
    def describe(cls, row):
        return f'{row} · {row.get_result_display()}'


class UnitAnswers(ReportRows):
    key, tab, label = 'units', 'units', _('Units of reduced capacity')
    formset = UnitAnswerFormSet
    kinds = (ReportKind.BIOMASS,)

    @classmethod
    def describe(cls, row):
        return row.unit.code if row.reduced_capacity else f'{row.unit.code} ({audit.english(_("No"))})'


class ReportResource(Resource):
    """Production › Reports › Regulatory reports: the reports and notices the farm files with the authorities. A
    report is computed from the records whenever it is shown; a person fills in what no record holds, files it
    themselves and records that they did, which freezes what was filed (reports/services.py)."""

    model = Report
    form_class = ReportForm
    name, plural = _('regulatory report'), _('regulatory reports')
    url_prefix = 'reports'
    list_template = 'reports/report_list.html'
    detail_template = 'reports/report_detail.html'
    form_template = 'reports/report_form.html'
    icon = 'file-text'
    page_size = 50
    row_lists = (TreatmentAnswers, ResistanceSuspicions, SensitivityTests, UnitAnswers)

    @classmethod
    def queryset(cls):
        return Report.objects.select_related('site', 'facility', 'submitted_by', 'corrects').annotate(
            has_filed_correction=Exists(Report.objects.filter(corrects=OuterRef('pk'), submitted_at__isnull=False)))

    @classmethod
    def form(cls, request, *args, **kwargs):
        """A new report starts with the person as its contact, and with what a due row gives it (?kind=&site= or
        &facility=, &period=2026-11)."""
        if not args and 'instance' not in kwargs and 'draft' not in kwargs:
            user = request.user
            initial = {'contact_name': user.get_full_name() or user.get_username(), 'contact_email': user.email}
            kind = request.GET.get('kind', '')
            if kind in compute.COMPUTE:
                initial['kind'] = kind
                for name, model in (('site', Site), ('facility', SlaughterFacility)):
                    chosen = request.GET.get(name, '')
                    if _is_uuid(chosen) and model.objects.filter(pk=chosen).exists():
                        initial[name] = chosen
                try:
                    initial['period_start'] = periods.Period.from_key(request.GET.get('period', '')).start
                except ValueError:
                    pass
            event = HealthEvent.objects.select_related('site').prefetch_related('units').filter(
                pk=request.GET.get('health_event', '')).first() if _is_uuid(request.GET.get('health_event', '')) \
                else None
            if event is not None:
                initial.update(_from_event(event, kind))
            escape = EscapeRecord.objects.select_related('operation').filter(
                pk=request.GET.get('escape', '')).first() if _is_uuid(request.GET.get('escape', '')) else None
            if escape is not None:
                initial.update(_from_escape(escape))
            kwargs['initial'] = initial
        return cls.form_class(*args, **kwargs)

    @classmethod
    def filter_list(cls, request, objects):
        objects, chosen_kind = filter_by(request, objects, 'kind', Report.Kind.choices, 'kind')
        sites = Site.objects.order_by('name')
        objects, chosen_site = filter_by(request, objects, 'site', sites, 'site')
        chosen_status = request.GET.get('status', '')
        if chosen_status == 'draft':
            objects = objects.filter(submitted_at__isnull=True)
        elif chosen_status == 'filed':
            objects = objects.filter(submitted_at__isnull=False)
        else:
            chosen_status = ''
        owed = due.due()
        rows, changed, lines = owed.rows, due.no_longer_match(), []
        if chosen_kind:
            rows = [row for row in rows if row.kind == chosen_kind]
            changed = [report for report in changed if report.kind == chosen_kind]
            lines = [line for line in owed.lines_of(chosen_kind)
                     if not chosen_site or line.place.pk == _uuid_or_none(chosen_site)
                     or not isinstance(line.place, Site)]
        start_url = reverse('reports:report_create') if request.user.has_perm(cls.perm('add')) else ''
        return objects, {'sites': sites, 'chosen_kind': chosen_kind,
                         'chosen_site': chosen_site, 'statuses': STATUSES, 'chosen_status': chosen_status,
                         'today': periods.oslo_today(), 'due': rows, 'changed': changed, 'lines': lines,
                         'not_set_up': [] if chosen_kind else owed.not_set_up,
                         'tabs': _tabs(request, owed.rows, chosen_kind),
                         'kind_start_url': f'{start_url}?kind={chosen_kind}' if start_url and chosen_kind else '',
                         'start_url': start_url}

    @classmethod
    def detail_extras(cls, request, report):
        """What the report says (as filed, once it is; else as the records give it now), what keeps it from being
        ready, how it differs from the records now, its deadline, and the filing form."""
        filed = getattr(report, 'snapshot', None) if report.submitted_at else None
        result = None if filed else compute.compute(report)
        deadline = compute.deadline(report)
        extras = {
            'content': filed.content if filed else result.content,
            'problems': [] if filed else result.problems,
            'warnings': [] if filed else result.warnings,
            'filed': filed,
            'deadline': deadline,
            'overdue': deadline is not None and report.submitted_at is None and periods.oslo_today() > deadline,
            'differences': services.differences(report) if filed else None,
            'corrections': report.corrections.filter(is_deleted=False).order_by('created_at'),
            'can_submit': report.submitted_at is None and request.user.has_perm(cls.perm('change')),
            'can_correct': report.submitted_at is not None and request.user.has_perm(cls.perm('add')),
            'export_urls': {fmt: reverse('reports:report_export', args=[report.pk, fmt]) for fmt in ('csv', 'json')},
            'print_url': reverse('reports:report_print', args=[report.pk]),
            'has_api': report.kind in exports.API_KINDS,
        }
        if extras['can_submit']:
            extras['submit_form'] = SubmitForm(initial={
                'submitted_at': timezone.localtime(timezone.now(), periods.OSLO).replace(
                    tzinfo=None, second=0, microsecond=0), 'version': report.version})
            extras['submit_url'] = reverse('reports:report_submit', args=[report.pk])
        if extras['can_correct']:
            extras['correct_url'] = reverse('reports:report_correct', args=[report.pk])
        return extras


def _tabs(request, rows, chosen_kind):
    """The tabs of the page: all the reports, then a tab for each kind, the urgent notices before the scheduled reports,
    each with the number of its reports due; a tab keeps the site and status filters."""
    kept = {name: request.GET[name] for name in ('site', 'status') if request.GET.get(name)}
    owed = {}
    for row in rows:
        owed[row.kind] = owed.get(row.kind, 0) + 1
    url = reverse('reports:report_list')

    def tab(label, kind, count=0):
        query = urlencode({**kept, **({'kind': kind} if kind else {})})
        return {'label': label, 'url': f'{url}?{query}' if query else url, 'current': chosen_kind == kind,
                'count': count}
    return [{'label': '', 'tabs': [tab(_('All reports'), '', len(rows))]},
            {'label': _('Urgent'), 'tabs': [tab(ReportKind(kind).label, kind, owed.get(kind, 0)) for kind in URGENT]},
            {'label': _('Scheduled'),
             'tabs': [tab(ReportKind(kind).label, kind, owed.get(kind, 0)) for kind in SCHEDULED]}]


def _uuid_or_none(value):
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


def _from_event(event, kind):
    """What a notice started from a health event begins with: its site and day, the kind it calls for (a listed disease
    is notified as a disease), and what the event says of what happened, the cause and the dead (the person's text
    from there on)."""
    units = ', '.join(unit.code for unit in event.units.all()) or _('the whole site')
    what = ' · '.join(str(part) for part in (event, event.get_confirmation_display() if event.confirmation else '',
                                              units) if part)
    deaths = with_deaths(HealthEvent.objects.filter(pk=event.pk)).get().deaths
    return {'kind': kind if kind in compute.COMPUTE else (
        ReportKind.DISEASE if event.notifiable else ReportKind.WELFARE),
        'site': event.site_id, 'health_event': event.pk, 'occurred_on': event.date, 'what_happened': what,
        'cause': event.get_diagnosis_display() if event.diagnosis else '', 'fish_dead': deaths or None}


def _from_escape(escape):
    """What an escape notice started from an escape begins with: its site and day, what it says of the fish, the cause
    and the number (the person's text from there on)."""
    line = escape.operation.movements.select_related('unit__production_department', 'batch__species').first()
    fish = -line.count_delta
    what = _('%(fish)d fish of %(species)s escaped from %(unit)s.') % {
        'fish': fish, 'species': line.batch.species, 'unit': line.unit.code}
    if escape.suspected:
        what = _('Suspected: %(what)s') % {'what': what}
    return {'kind': ReportKind.ESCAPE, 'site': line.unit.production_department.site_id, 'escape': escape.pk,
            'occurred_on': escape.operation.date, 'what_happened': what, 'cause': escape.cause,
            'fish_involved': fish, 'situation': escape.health_status}


def _is_uuid(value):
    try:
        uuid.UUID(str(value))
    except ValueError:
        return False
    return True
