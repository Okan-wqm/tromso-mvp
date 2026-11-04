"""The two acts on a report that are not edits of its form: recording that it was filed, which freezes its content,
and starting a correction of a filed one. Each locks the report, checks it, writes and logs in one transaction."""
from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from core import audit
from core.models import AuditLog

from . import compute, due, periods
from .kinds import EVENTS
from .models import NARRATIVE, WITHOUT_REFERENCE, Channel, DueClosure, Report, ReportSnapshot

# The format of a notice that was recorded on the health event before notices existed (its time only).
LEGACY_FORMAT = 0

# The leaves of a content that name rather than count: a change of one is "identity changed since filing".
IDENTITY_LEAVES = ('/number', '/species', '/organisation_number', '/lokalitetsnummer', '/site', '/site_code')

# The answers a correction starts from: the report's own (the row lists are copied too).
CARRIED = ('contact_name', 'contact_email', 'contact_phone', *NARRATIVE, 'notes')
ROW_LISTS = ('treatment_answers', 'resistance_suspicions', 'sensitivity_tests', 'unit_answers')
ROW_FIELDS = {
    'treatment_answers': ('treatment_id', 'done_before_count', 'combination'),
    'resistance_suspicions': ('substance', 'other_substance', 'cause', 'other_cause'),
    'sensitivity_tests': ('tested_on', 'laboratory', 'substance', 'other_substance', 'result'),
    'unit_answers': ('unit_id', 'reduced_capacity'),
}


def _refuse(message):
    raise ValidationError({NON_FIELD_ERRORS: [message]})


def submit(user, report, *, submitted_at, channel, reference, version, content_sha256):
    """Records that `report` was filed (when, how, the receipt) and freezes its content as it is computed now: the content
    the person was shown, named by its hash (`content_sha256`, what the page and the print gave before the filing). Refused
    for a stale form, a report already filed, one not ready (its problems), a time in the future, a channel with a
    receipt but none given, or when the records now give another content than the one that was shown (a backdated
    record in between): the person looks again, and what is frozen is always what was previewed."""
    with transaction.atomic():
        current = Report.objects.select_for_update().get(pk=report.pk)
        if current.version != version:
            _refuse(_('Someone else changed this report while you were looking at it: look again before you record '
                      'the filing.'))
        if current.submitted_at is not None:
            _refuse(_('It was filed already.'))
        if submitted_at > timezone.now():
            raise ValidationError({'submitted_at': [_('The time cannot be in the future.')]})
        if not reference.strip() and channel not in WITHOUT_REFERENCE:
            raise ValidationError({'reference': [_('Give the receipt or reference the authority gave.')]})
        result = compute.compute(current)
        # A notice given by telephone is recorded as it was told: its figures may not all be in the records yet, and
        # what is missing is kept with the filing rather than keeping the call from being recorded.
        phoned = channel == Channel.TELEPHONE and current.kind in EVENTS
        if result.problems and not phoned:
            _refuse(_('It is not ready: %(problems)s') % {'problems': ' '.join(result.problems)})
        logged = result.problems
        if logged:
            with audit.source_language():      # the log is English at rest, whoever records the filing
                logged = compute.compute(current).problems
        digest = compute.content_hash(result.content)
        if digest != content_sha256:
            _refuse(_('The records changed after you looked at the report: review it again before you record the '
                      'filing.'))
        ReportSnapshot.objects.create(report=current, format_version=compute.FORMAT_VERSION, content=result.content,
                                      content_sha256=digest, sources_fingerprint=compute.fingerprint(result.scope))
        current.submitted_at, current.submitted_by = submitted_at, user
        current.channel, current.reference = channel, reference.strip()
        current.updated_by, current.version = user, current.version + 1
        current.save()
        with audit.source_language():
            changes = {
                str(_('Status')): [audit.message(_('Draft')), audit.message(_('Filed'))],
                str(Report._meta.get_field('submitted_at').verbose_name): [None, submitted_at.isoformat()],
                str(Report._meta.get_field('submitted_by').verbose_name): [None, user.get_username()],
                str(Report._meta.get_field('channel').verbose_name): [None, audit.message(current.get_channel_display())],
                str(Report._meta.get_field('reference').verbose_name): [None, current.reference or None],
                str(_('Content hash')): [None, digest],
                **({str(_('Not ready when filed')): [None, ' '.join(logged)]} if logged else {}),
            }
            audit.record(user, AuditLog.Action.UPDATE, current, changes, entity_type=Report._meta.verbose_name)
    return current


def close_due(user, *, kind, place, period, reason):
    """Closes a report that is owed and will not be filed, with the reason: the due list stops listing it. Refused when
    nothing is owed there (it was filed, or is not due), or without a reason. Logged; `reopen` undoes it."""
    if not reason.strip():
        raise ValidationError({'reason': [_('Say why it is closed.')]})
    if not any(row.kind == kind and row.place == place and row.period == period for row in due.due().rows):
        _refuse(_('Nothing is owed there: it was filed, closed already or is not due.'))
    with transaction.atomic():
        closure = DueClosure(kind=kind, period_start=period.start, reason=reason.strip(), closed_by=user,
                             **{'facility' if kind == 'slaughter_planned' else 'site': place})
        closure.full_clean()
        closure.save()
        with audit.source_language():
            audit.record_create(user, closure, {
                str(_('Report')): audit.message(closure.get_kind_display()), str(_('Site')): closure.site and str(closure.site),
                str(_('Slaughter facility')): closure.facility and str(closure.facility),
                str(_('Period')): closure.period_start.isoformat(), str(_('Why it is closed')): closure.reason})
    return closure


def reopen(user, closure):
    """Takes a closure away: the report is owed again. Logged."""
    with transaction.atomic():
        pk = closure.pk
        with audit.source_language():
            audit.record(user, AuditLog.Action.DELETE, closure, entity_type=DueClosure._meta.verbose_name,
                         label=audit.english(closure))
        closure.delete()
    return pk


def start_correction(user, report):
    """A new draft that corrects the filed `report`: its key and its answers, to be checked against the records as
    they are now and filed again. Refused for a report not filed or one that already has a live correction."""
    from .resources import ReportResource
    with transaction.atomic():
        original = Report.objects.select_for_update().get(pk=report.pk)
        if original.submitted_at is None:
            _refuse(_('Only a filed report is corrected: change the draft itself.'))
        if original.corrections.filter(is_deleted=False).exists():
            _refuse(_('This report already has a correction: open it from the list.'))
        draft = Report(kind=original.kind, site=original.site, facility=original.facility,
                       period_start=original.period_start, occurred_on=original.occurred_on,
                       health_event=original.health_event, escape=original.escape, corrects=original,
                       created_by=user, updated_by=user, **{name: getattr(original, name) for name in CARRIED})
        draft.full_clean()
        draft.save()
        for related in ROW_LISTS:
            rows = getattr(original, related).all()
            model = rows.model
            model.objects.bulk_create([model(report=draft, created_by=user, **{
                name: getattr(row, name) for name in ROW_FIELDS[related]}) for row in rows])
        audit.record_create(user, draft, ReportResource.recorded(draft), entity_type=ReportResource.entity_type())
    return draft


def differences(report):
    """What the records give now against what was filed: [(path, filed, now)] of the figures, of the identity (a
    unit's number, a species' code, the site's numbers renamed since) and of the sources read, and whether the
    format changed. Read on the report's page; nothing is stored."""
    snapshot = report.snapshot
    if snapshot.format_version == LEGACY_FORMAT:
        return {'figures': [], 'identity': [], 'sources': [], 'format_changed': False, 'legacy': True}
    now = compute.compute(report).content
    before, after = compute.flatten(snapshot.content), compute.flatten(now)
    figures, identity, sources = [], [], []
    for path in sorted(set(before) | set(after)):
        if before.get(path) == after.get(path):
            continue
        item = (path, before.get(path), after.get(path))
        if path.endswith(('/lines', '/items')) or '/lines/' in path or '/items/' in path:
            sources.append(item)
        elif '/identity/' in path or path.startswith('/facility/') or path.endswith(IDENTITY_LEAVES):
            identity.append(item)
        else:
            figures.append(item)
    return {'figures': figures, 'identity': identity, 'sources': sources,
            'format_changed': snapshot.format_version != compute.FORMAT_VERSION}
