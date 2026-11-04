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

from . import compute, due, exports, periods, services
from .forms import CloseForm, SubmitForm
from .kinds import ReportKind
from .models import DueClosure
from .resources import ReportResource


def _report(pk):
    return get_object_or_404(ReportResource.queryset(), pk=pk)


def _content(report):
    """The content a page or a file shows: the frozen one once the report is filed, else the records' now."""
    if report.submitted_at is not None:
        return report.snapshot.content, True
    return compute.compute(report).content, False


UPCOMING = 6


def overview_upcoming(user):
    """The company overview's upcoming reports: the next deadlines of what is due, the overdue first (the due list, read as
    the Reports page reads it), for people who may read the reports; None for the others."""
    if not user.has_perm('reports.view_report'):
        return None
    rows = due.due().rows
    return {'rows': rows[:UPCOMING], 'more': max(len(rows) - UPCOMING, 0), 'url': reverse('reports:report_list'),
            'overdue': sum(1 for row in rows if row.overdue)}


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


def _due_row(request):
    """The due row a closing link names (?kind=&site= or &facility=, &period=): None when it is not owed."""
    kind, period = request.GET.get('kind', ''), request.GET.get('period', '')
    try:
        found = periods.Period.from_key(period)
    except ValueError:
        return None
    key = 'facility' if kind == ReportKind.SLAUGHTER_PLANNED else 'site'
    for row in due.due().rows:
        if row.kind == kind and row.period == found and str(row.place.pk) == request.GET.get(key, ''):
            return row
    return None


@permission_required('reports.change_report', raise_exception=True)
def close(request):
    """Closes a report that is owed and will not be filed, with the reason (a dialog)."""
    row = _due_row(request)
    if row is None:
        raise Http404
    place = navigation.place(ReportResource.perm('view'))
    back = reverse('reports:report_list') + f'?kind={row.kind}'
    context = {'row': row, 'heading': _('Close without filing'), 'back_url': back, 'title': _('Close without filing'),
               'eyebrow': f'{place.heading} · {place.entry.label}'}
    if request.method == 'POST':
        form = CloseForm(request.POST)
        if form.is_valid():
            try:
                services.close_due(request.user, kind=row.kind, place=row.place, period=row.period,
                                   reason=form.cleaned_data['reason'])
            except ValidationError as error:
                for field, texts in error.message_dict.items():
                    for text in texts:
                        form.add_error(field if field in form.fields else None, text)
            else:
                messages.success(request, _('Closed: it is not owed any more. It can be reopened from its tab.'))
                return done(request, back)
        response = render_page(request, 'reports/close_due.html', {**context, 'form': form})
        response.status_code = 422
        return response
    return render_page(request, 'reports/close_due.html', {**context, 'form': CloseForm()})


@permission_required('reports.change_report', raise_exception=True)
@require_POST
def reopen(request, pk):
    """Takes a closure away: the report is owed again."""
    closure = get_object_or_404(DueClosure, pk=pk)
    kind = closure.kind
    services.reopen(request.user, closure)
    messages.success(request, _('Reopened: it is owed again.'))
    return done(request, reverse('reports:report_list') + f'?kind={kind}')


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

