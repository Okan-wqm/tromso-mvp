"""The pages of Administration › Database: the tables (core.database) and one table's data and
structure (core.dbgrid). Strictly read-only: only GET (and HEAD) is accepted, and nothing here writes but the read
log's row of an export (core.AccessEvent, with the reason typed for it)."""
import csv
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import permission_required
from django.http import Http404, StreamingHttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_safe

from . import database, sealing
from .models import AccessEvent
from .dbgrid import DELETED_MODES, EXPORT_LIMIT, Grid


def platform_admin_only(view):
    return permission_required(database.PERMISSION, raise_exception=True)(require_safe(view))


def shown_table(name):
    table = database.find(name)
    if table is None:
        raise Http404('No such table.')
    return table


@platform_admin_only
def overview(request):
    return render(request, 'core/database/overview.html', {
        'sections': [{'label': label, 'tables': [{'table': table, **table.counts()} for table in tables]}
                     for label, tables in database.sections() if tables],
    })


@platform_admin_only
def browse(request, name):
    table = shown_table(name)
    structure = table.structure()
    return render(request, 'core/database/table.html', {
        'table': table, 'counts': table.counts(), 'structure': structure,
        'grid': Grid(table, structure, request.GET),
        'deleted_modes': DELETED_MODES, 'export_limit': EXPORT_LIMIT,
    })


class Echo:
    """The 'file' a csv writer writes to: it hands each line back instead of keeping it."""

    def write(self, line):
        return line


def csv_lines(rows):
    writer = csv.writer(Echo())
    yield '\ufeff'   # the byte order mark Excel needs to read the UTF-8 (æ, ø, å)
    for row in rows:
        yield writer.writerow(row)


@platform_admin_only
def export(request, name):
    """The rows of the view as CSV, for a typed reason (owner decision C2.2), each export in the read log."""
    table = shown_table(name)
    reason = ' '.join(request.GET.get('reason', '').split())[:300]
    if not reason:
        messages.error(request, _('Say why you export it.'))
        query = urlencode([(key, value) for key, value in request.GET.items() if key != 'reason'])
        return redirect(reverse('core:database_table', args=[name]) + (f'?{query}' if query else ''))
    sealing.log_access(AccessEvent.Kind.EXPORT, 'table', table.name, route='core:database_export', reason=reason)
    response = StreamingHttpResponse(csv_lines(Grid(table, table.structure(), request.GET).export()),
                                     content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{table.name}.csv"'
    return response
