"""Every rule of the reports, checked from scratch over all of them (the way farm/stock/integrity.py checks the stock): what
a filed report keeps is what it was filed with. The services, the forms and the database's triggers hold these on every write;
this finds a row that got past them (a hand edit with the triggers off, a bug). `manage.py check_reports` prints what it
finds; the tests run it after their writes. Its messages are for the developer, in English."""
from farm.models import EscapeRecord

from .compute import FORMAT_VERSION
from .compute.common import content_hash
from .models import Report, ReportSnapshot

LEGACY = 0           # the format of a notice recorded on the health event before notices existed


def problems():
    """Every broken rule of the reports, as sentences; empty when they add up."""
    found = []
    snapshots = {snapshot.report_id: snapshot for snapshot in ReportSnapshot.objects.all()}
    reports = list(Report.all_objects.select_related('site', 'facility', 'health_event', 'corrects'))
    for report in reports:
        name = f'{report.get_kind_display()} {report.pk}'
        snapshot = snapshots.get(report.pk)
        if report.submitted_at is None:
            if snapshot is not None:
                found.append(f'{name} is a draft and has a frozen content.')
        elif snapshot is None:
            found.append(f'{name} was filed and has no frozen content.')
        else:
            if snapshot.format_version not in (LEGACY, FORMAT_VERSION):
                found.append(f'{name} has a content of format {snapshot.format_version}, which this version does not know.')
            if snapshot.content_sha256 != content_hash(snapshot.content):
                found.append(f'{name}: the frozen content does not match its hash.')
        if report.corrects_id is not None:
            original = report.corrects
            if original.submitted_at is None:
                found.append(f'{name} corrects {original.pk}, which was never filed.')
            same = (original.kind, original.site_id, original.facility_id, original.period_start, original.occurred_on,
                    original.health_event_id, original.escape_id) == (
                report.kind, report.site_id, report.facility_id, report.period_start, report.occurred_on,
                report.health_event_id, report.escape_id)
            if not same:
                found.append(f'{name} corrects {original.pk}, which is not of the same report.')
        if report.health_event_id and report.site_id and report.health_event.site_id != report.site_id:
            found.append(f'{name} is of a site other than its health event’s.')
        if report.escape_id and report.site_id:
            line = EscapeRecord.all_objects.get(pk=report.escape_id).operation.movements.select_related(
                'unit__production_department').first()
            if line is None or line.unit.production_department.site_id != report.site_id:
                found.append(f'{name} is of a site other than its escape’s.')
    report_ids = {report.pk for report in reports}
    for report_id in snapshots:
        if report_id not in report_ids:
            found.append(f'A frozen content belongs to no report ({report_id}).')
    return found
