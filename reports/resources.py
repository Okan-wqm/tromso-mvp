import uuid

from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _, ngettext_lazy

from core import audit
from core.crud import Resource, RowList, filter_by
from farm.models import SlaughterFacility, Site

from . import compute, periods, services
from .forms import ReportForm, ResistanceSuspicionFormSet, SensitivityTestFormSet, SubmitForm, UnitAnswerFormSet
from .kinds import ReportKind
from .models import Report

STATUSES = [('draft', _('Draft')), ('filed', _('Filed'))]


class ReportRows(RowList):
    """A list of answers of a report, edited while it is a draft (a database trigger refuses it once filed)."""
    kinds = ()
    saved = ngettext_lazy('%(count)d row saved.', '%(count)d rows saved.', 'count')

    @classmethod
    def applies_to(cls, report):
        return report.kind in cls.kinds and report.submitted_at is None


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
    row_lists = (ResistanceSuspicions, SensitivityTests, UnitAnswers)

    @classmethod
    def queryset(cls):
        return Report.objects.select_related('site', 'facility', 'submitted_by', 'corrects')

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
        return objects, {'kinds': Report.Kind.choices, 'chosen_kind': chosen_kind, 'sites': sites,
                         'chosen_site': chosen_site, 'statuses': STATUSES, 'chosen_status': chosen_status,
                         'today': periods.oslo_today()}

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
        }
        if extras['can_submit']:
            extras['submit_form'] = SubmitForm(initial={
                'submitted_at': timezone.localtime().replace(second=0, microsecond=0), 'version': report.version})
            extras['submit_url'] = reverse('reports:report_submit', args=[report.pk])
        if extras['can_correct']:
            extras['correct_url'] = reverse('reports:report_correct', args=[report.pk])
        return extras


def _is_uuid(value):
    try:
        uuid.UUID(str(value))
    except ValueError:
        return False
    return True
