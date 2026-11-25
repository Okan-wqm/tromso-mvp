"""The two acts on a report that are not edits of its form: recording that it was filed, which freezes its content,
and starting a correction of a filed one. Each locks the report, checks it, writes and logs in one transaction."""
from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from core import access, audit
from farm.models import Batch, Tank
from farm.stock import read as stock_read
from farm.models.species import SALMONID_CODES
from core.models import AuditLog

from . import compute, due, labels, periods
from .kinds import EVENTS
from .models import (
    NARRATIVE, WITHOUT_REFERENCE, Channel, DueClosure, OpenQuestion, OutsideDutyDone, QuestionStatus, Report,
    ReportSnapshot,
)

# Who may (asked by each act itself, whoever calls: the data-layering audit, L-6): the report pages' rights.
CHANGE, ADD = 'reports.change_report', 'reports.add_report'

# The format of a notice that was recorded on the health event before notices existed (its time only).
LEGACY_FORMAT = 0

# The leaves of a content that name rather than count (reports/labels.py, which also prints them as written): a change
# of one is "identity changed since filing".
IDENTITY_LEAVES = labels.IDENTITY_LEAVES

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


def submit(user, report, *, submitted_at, channel, reference, version, content_sha256, acknowledged=(),
           authority_id=''):
    """Records that `report` was filed (when, how, the receipt) and freezes its content as it is computed now: the content
    the person was shown, named by its hash (`content_sha256`, what the page and the print gave before the filing). Refused
    for a stale form, a report already filed, one not ready (its problems), a time in the future, a channel with a
    receipt but none given, when the records now give another content than the one that was shown (a backdated
    record in between): the person looks again, and what is frozen is always what was previewed, or when the content rests
    on a question for the authority that is still open (`acknowledged`: the numbers the person confirmed by hand), which is
    logged with the question's text."""
    access.require(user, CHANGE)
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
        unconfirmed = OpenQuestion.objects.filter(code__in=result.questions, status=QuestionStatus.OPEN)
        missing = [question for question in unconfirmed if question.code not in acknowledged]
        if missing:
            raise ValidationError({'acknowledged': [_('Open question %(code)s: %(question)s Confirm that you checked '
                                                      'this by hand before you record the filing.') % {
                'code': question.code, 'question': question.question} for question in missing]})
        digest = compute.content_hash(result.content)
        if digest != content_sha256:
            _refuse(_('The records changed after you looked at the report: review it again before you record the '
                      'filing.'))
        ReportSnapshot.objects.create(report=current, format_version=compute.FORMAT_VERSION, content=result.content,
                                      content_sha256=digest, sources_fingerprint=compute.fingerprint(result.scope),
                                      scope_version=compute.scope_version(current.kind))
        current.deadline_on = compute.deadline(current)
        current.filed_late = (periods.oslo_today(submitted_at) > current.deadline_on) if current.deadline_on else False
        current.submitted_at, current.submitted_by = submitted_at, user
        current.channel, current.reference = channel, reference.strip()
        current.authority_id = authority_id.strip()
        current.updated_by, current.version = user, current.version + 1
        current.save()
        with audit.source_language():
            changes = {
                str(_('Status')): [audit.message(_('Draft')), audit.message(_('Filed'))],
                str(Report._meta.get_field('submitted_at').verbose_name): [None, submitted_at.isoformat()],
                str(Report._meta.get_field('submitted_by').verbose_name): [None, user.get_username()],
                str(Report._meta.get_field('channel').verbose_name): [None, audit.message(current.get_channel_display())],
                str(Report._meta.get_field('reference').verbose_name): [None, current.reference or None],
                str(Report._meta.get_field('authority_id').verbose_name): [None, current.authority_id or None],
                str(_('Content hash')): [None, digest],
                str(Report._meta.get_field('deadline_on').verbose_name): [None, current.deadline_on and
                                                                            current.deadline_on.isoformat()],
                str(Report._meta.get_field('filed_late').verbose_name): [None, audit.message(
                    _('Yes') if current.filed_late else _('No'))],
                **({str(_('Not ready when filed')): [None, ' '.join(logged)]} if logged else {}),
                **({str(_('Open questions acknowledged')): [None, '; '.join(
                    f'{question.code}: {question.question}' for question in unconfirmed)]} if unconfirmed else {}),
            }
            audit.record(user, AuditLog.Action.UPDATE, current, changes, entity_type=Report._meta.verbose_name)
    return current


def close_due(user, *, kind, place, period, reason):
    """Closes a report that is owed and will not be filed, with the reason: the due list stops listing it. Refused when
    nothing is owed there (it was filed, or is not due), or without a reason. Logged; `reopen` undoes it."""
    access.require(user, CHANGE)
    if not reason.strip():
        raise ValidationError({'reason': [_('Say why it is closed.')]})
    with transaction.atomic():
        # Owed is read inside the transaction that closes it (the data-layering audit, L-13), so the read and the
        # closure are one unit. No row is locked: under READ COMMITTED a closure or a filing that commits while this
        # runs is not seen; the closure's own unique constraint is what refuses a second one at the same moment.
        if not any(row.kind == kind and row.place == place and row.period == period for row in due.due().rows):
            _refuse(_('Nothing is owed there: it was filed, closed already or is not due.'))
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


def _take_away(user, model, row):
    """Deletes a closure or a duty done once: the row locked first, refused when it is gone already (a second press on a
    page shown before the first), logged after it is gone (audit F-077)."""
    with transaction.atomic():
        found = model.objects.select_for_update().filter(pk=row.pk).first()
        if found is None:
            _refuse(_('It was taken away already.'))
        pk, label = found.pk, audit.english(found)
        found.delete()
        found.pk = pk
        with audit.source_language():
            audit.record(user, AuditLog.Action.DELETE, found, entity_type=model._meta.verbose_name, label=label)
    return pk


def reopen(user, closure):
    """Takes a closure away: the report is owed again. Logged."""
    access.require(user, CHANGE)
    return _take_away(user, DueClosure, closure)


def record_duty_done(user, *, duty, site, year, done_on, reference=''):
    """Records that an annual duty outside this system was done for a site and a year (not a report; nothing is sent). Refused when
    the duty does not bind the site, or the day is in the future. Logged."""
    access.require(user, CHANGE)
    from . import duties
    found = duties.BY_CODE.get(duty)
    if found is None or not found.recordable:
        _refuse(_('This duty is not recorded here.'))
    if done_on > periods.oslo_today():
        raise ValidationError({'done_on': [_('The day cannot be in the future.')]})
    salmonids = any(batch.species.official_code in SALMONID_CODES for batch in Batch.objects.filter(
        pk__in=stock_read.batches_ever_in(Tank.all_objects.filter(production_department__site=site)
                                          .values_list('pk', flat=True))).select_related('species'))
    if not duties.applies(found, site, salmonids)[0]:
        _refuse(_('This duty does not bind this site.'))
    with transaction.atomic():
        record = OutsideDutyDone(duty=duty, site=site, year=year, done_on=done_on, reference=reference.strip(),
                                 recorded_by=user)
        record.full_clean()
        record.save()
        with audit.source_language():
            audit.record_create(user, record, {
                str(_('Duty')): audit.message(record.get_duty_display()), str(_('Site')): str(site),
                str(_('Year')): str(year), str(_('Done on')): done_on.isoformat(),
                str(_('Receipt or reference')): record.reference or None})
    return record


def undo_duty_done(user, record):
    """Takes a record away: the duty is owed again. Logged."""
    access.require(user, CHANGE)
    _take_away(user, OutsideDutyDone, record)


def start_correction(user, report):
    """A new draft that corrects the filed `report`: its key and its answers, to be checked against the records as
    they are now and filed again. Refused for a report not filed or one that already has a live correction."""
    access.require(user, ADD)
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
    unit's number, a species' code, the site's numbers renamed since) and of the sources read, whether the format
    changed, and `labels`, each path as the page names it (reports/labels.py). Read on the report's page; nothing is
    stored."""
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
            'format_changed': snapshot.format_version != compute.FORMAT_VERSION,
            'labels': {path: labels.describe(path, snapshot.content, now) for path, _filed, _now in figures + identity}}
