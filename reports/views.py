"""The acts on a report beside its form (core.crud.Resource): recording the filing (Edit), starting a correction
(Create), and the exports and the print page (Read)."""
import json

from django.contrib import messages
from django.contrib.auth.decorators import permission_required
from django.core.exceptions import ValidationError
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.utils.http import content_disposition_header
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from core import navigation
from core.crud import done, render_page

from . import compute, exports, periods, services
from .forms import SubmitForm
from .resources import ReportResource


def _report(pk):
    return get_object_or_404(ReportResource.queryset(), pk=pk)


def _content(report):
    """The content a page or a file shows: the frozen one once the report is filed, else the records' now."""
    if report.submitted_at is not None:
        return report.snapshot.content, True
    return compute.compute(report).content, False


@permission_required('reports.change_report', raise_exception=True)
@require_POST
def submit(request, pk):
    """Records that the report was filed (when, how, the receipt) and freezes its content (reports/services.py)."""
    report = _report(pk)
    form = SubmitForm(request.POST)
    detail = reverse('reports:report_detail', args=[report.pk])
    if form.is_valid():
        try:
            filed = {**form.cleaned_data, 'submitted_at': timezone.make_aware(form.cleaned_data['submitted_at'],
                                                                           periods.OSLO)}
            services.submit(request.user, report, **filed)
        except ValidationError as error:
            for messages_of_field in error.message_dict.values():
                for text in messages_of_field:
                    messages.error(request, text)
        else:
            messages.success(request, _('Recorded as filed. What was filed is kept as it is.'))
    else:
        for field, errors in form.errors.items():
            for text in errors:
                messages.error(request, f'{form.fields[field].label}: {text}' if field in form.fields else text)
    return done(request, detail)


@permission_required('reports.add_report', raise_exception=True)
@require_POST
def correct(request, pk):
    """Starts a correction of a filed report and opens it."""
    report = _report(pk)
    try:
        draft = services.start_correction(request.user, report)
    except ValidationError as error:
        for text in error.messages:
            messages.error(request, text)
        return done(request, reverse('reports:report_detail', args=[report.pk]))
    messages.success(request, _('Correction started: check it against the records and file it again.'))
    return done(request, reverse('reports:report_edit', args=[draft.pk]), stay=True)


@permission_required('reports.view_report', raise_exception=True)
def export(request, pk, fmt):
    """The report as CSV, or as JSON in the shape of Mattilsynet's reporting API for the kinds it takes."""
    report = _report(pk)
    content, filed = _content(report)
    name = f'{report.kind}-{report.site.code if report.site else report.facility.approval_number}-' \
           f'{report.period.key if report.period else report.occurred_on}{"" if filed else "-not-filed"}'
    if fmt == 'csv':
        response = HttpResponse(exports.csv_text(report, content), content_type='text/csv; charset=utf-8')
    elif fmt == 'json':
        shaped = exports.api_json(report, content)
        if shaped is None:
            raise Http404
        response = HttpResponse(json.dumps(shaped, ensure_ascii=False, indent=2),
                                content_type='application/json; charset=utf-8')
    else:
        raise Http404
    response['Content-Disposition'] = content_disposition_header(True, f'{name}.{fmt}')
    return response


@permission_required('reports.view_report', raise_exception=True)
def print_page(request, pk):
    """The report on one page to print or to type from, in the authority's order."""
    report = _report(pk)
    content, filed = _content(report)
    place = navigation.place(ReportResource.perm('view'))
    return render_page(request, 'reports/report_print.html', {
        'object': report, 'content': content, 'filed': filed, 'title': str(report),
        'eyebrow': f'{place.heading} · {place.entry.label}',
        'rows': exports.rows(report, content), 'list_url': reverse('reports:report_list'),
        'detail_url': reverse('reports:report_detail', args=[report.pk]),
    })

