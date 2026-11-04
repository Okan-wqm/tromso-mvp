"""Regulatory reports (Production › Reports): a report a person files with an authority, its frozen content once filed,
and the few answers no record holds. Every figure of a report is computed from the farm's records on read
(reports/compute); nothing here holds a count, a weight or a feed amount (docs/regulatory-reports.md, section 5)."""
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q
from django.utils.translation import gettext, gettext_lazy as _

from core.models import AuditedModel
from farm.models import EscapeRecord, HealthEvent, SlaughterFacility, Site, Tank, Treatment

from . import periods
from .kinds import BY_FACILITY, EVENTS, KINDS, PERIODIC, ReportKind, info

SHA256 = r'^[0-9a-f]{64}$'


class HarvestCondition(models.TextChoices):
    """The condition of the harvested fish the biomass report's slaughter weights are given in (`slaktetilstand`)."""
    ROUND = 'round', _('Round weight (as weighed at harvest)')
    GUTTED = 'gutted', _('Gutted weight')


class Channel(models.TextChoices):
    """How the person filed the report: the system sends nothing (docs/regulatory-reports.md, 5.1)."""
    ALTINN = 'altinn', _('Altinn form')
    API = 'api', _('Reporting API, from another system')
    EMAIL = 'email', _('E-mail')
    TELEPHONE = 'telephone', _('Telephone')
    OTHER = 'other', _('Other')


# A notice phoned in at once has no receipt; a filing through a form or an e-mail has one.
WITHOUT_REFERENCE = (Channel.TELEPHONE, Channel.OTHER)

# The narrative of an event notice: what the person told the authority, on the report's own form.
NARRATIVE = ('what_happened', 'found_at', 'cause', 'fish_dead', 'fish_injured', 'fish_involved', 'situation',
             'measures')
NARRATIVE_KINDS = (ReportKind.ESCAPE, ReportKind.DISEASE, ReportKind.WELFARE)
SITE_NOTICES = (ReportKind.SITE_IN_USE, ReportKind.SITE_EMPTIED)
HEALTH_EVENT_KINDS = (ReportKind.DISEASE, ReportKind.WELFARE)
WEEKLY = tuple(kind for kind in PERIODIC if KINDS[kind].grain == periods.WEEK)
MONTHLY = tuple(kind for kind in PERIODIC if KINDS[kind].grain == periods.MONTH)
YEARLY = tuple(kind for kind in PERIODIC if KINDS[kind].grain == periods.YEAR)


def _check(name, condition, message=None):
    return models.CheckConstraint(condition=condition, name=f'chk_regulatory_reports_{name}',
                                  **({'violation_error_message': message} if message else {}))


class Report(AuditedModel):
    """A report to an authority for a site (a slaughter facility for the planned slaughter) and a period, or a notice
    of an event. A draft until a person records that they filed it (`submitted_at`, by, how, the receipt): then its
    content is frozen (ReportSnapshot) and the row never changes again (a database trigger); a mistake found later
    is a correction, a new report that `corrects` it. Its status is derived, never stored.

    What a report says comes from the records, read when it is shown (reports/compute); the person adds only what
    no record holds: the contact person, an event's narrative, and the answers of the row lists (the lice report's
    resistance suspicions and sensitivity tests, the biomass report's reduced-capacity units). An event's site is
    taken from the event when the report is started, and a report's key (kind, site, facility, period, event,
    corrected report) is fixed once it exists."""

    Kind = ReportKind
    Channel = Channel

    kind = models.CharField(_('Report'), max_length=20, choices=ReportKind.choices)
    site = models.ForeignKey(Site, null=True, blank=True, on_delete=models.PROTECT, related_name='regulatory_reports',
                             verbose_name=_('Site'))
    facility = models.ForeignKey(SlaughterFacility, null=True, blank=True, on_delete=models.PROTECT,
                                 related_name='regulatory_reports', verbose_name=_('Slaughter facility'))
    period_start = models.DateField(_('Period'), null=True, blank=True)
    # The health event a notice is about: a disease notice's, a welfare notice's when it came of one (D-4: that
    # Mattilsynet was told of the event is this notice's filing, which the health records read).
    health_event = models.ForeignKey(HealthEvent, null=True, blank=True, on_delete=models.PROTECT,
                                     related_name='notices', verbose_name=_('Health event'))
    # The escape an escape notice reports (farm/models/stock.py EscapeRecord).
    escape = models.ForeignKey(EscapeRecord, null=True, blank=True, on_delete=models.PROTECT,
                               related_name='notices', verbose_name=_('Escape'))
    occurred_on = models.DateField(_('Happened on'), null=True, blank=True)

    contact_name = models.CharField(_('Contact person'), max_length=255, blank=True)
    contact_email = models.EmailField(_('Contact e-mail'), max_length=255, blank=True)
    contact_phone = models.CharField(_('Contact telephone'), max_length=40, blank=True)

    what_happened = models.CharField(_('What happened'), max_length=4000, blank=True)
    found_at = models.DateTimeField(_('Found at'), null=True, blank=True)
    cause = models.CharField(_('Cause'), max_length=2000, blank=True)
    fish_dead = models.PositiveIntegerField(_('Fish dead'), null=True, blank=True)
    fish_injured = models.PositiveIntegerField(_('Fish injured'), null=True, blank=True)
    fish_involved = models.PositiveIntegerField(_('Fish involved'), null=True, blank=True)
    situation = models.CharField(_('The situation now'), max_length=2000, blank=True)
    measures = models.CharField(_('Measures taken'), max_length=2000, blank=True)

    corrects = models.ForeignKey('self', null=True, blank=True, on_delete=models.PROTECT, related_name='corrections',
                                 verbose_name=_('Corrects'))

    submitted_at = models.DateTimeField(_('Filed at'), null=True, blank=True)
    # People are deactivated, never deleted (README, Roles and users): whoever recorded a filing stays named.
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                     related_name='+', verbose_name=_('Recorded by'))
    channel = models.CharField(_('Filed through'), max_length=20, blank=True, choices=Channel.choices)
    reference = models.CharField(_('Receipt or reference'), max_length=200, blank=True)
    notes = models.CharField(_('Notes'), max_length=2000, blank=True)
    # The two facts no record holds that a monthly report needs said: in what condition the harvest weights of the biomass
    # report are given, and that no feed was given to the cleaner fish (so that 0 kg is a statement, not a silence).
    harvest_condition = models.CharField(_('Condition of the harvested fish'), max_length=10, blank=True,
                                         choices=HarvestCondition.choices)
    no_cleaner_feed = models.BooleanField(_('No feed was given to the cleaner fish'), default=False)
    # Set when the filing is recorded: the deadline then, and whether the filing came after it (the day in Oslo). Empty for a
    # notice (filed at once) and for a filing recorded before this was kept.
    deadline_on = models.DateField(_('Deadline'), null=True, blank=True)
    filed_late = models.BooleanField(_('Filed late'), null=True, blank=True)

    class Meta:
        db_table = 'regulatory_reports'
        ordering = ['-period_start', '-occurred_on', '-created_at']
        verbose_name = _('regulatory report')
        verbose_name_plural = _('regulatory reports')
        constraints = [
            _check('kind', Q(kind__in=ReportKind.values)),
            _check('scope', Q(kind__in=BY_FACILITY, facility__isnull=False, site__isnull=True)
                   | (~Q(kind__in=BY_FACILITY) & Q(site__isnull=False, facility__isnull=True)),
                   _('A planned slaughter is reported for a slaughter facility, every other report for a site.')),
            _check('when', Q(kind__in=PERIODIC, period_start__isnull=False, occurred_on__isnull=True)
                   | Q(kind__in=EVENTS, period_start__isnull=True),
                   _('A report is for a period, a notice for an event.')),
            _check('week', ~Q(kind__in=WEEKLY) | Q(period_start__iso_week_day=1)),
            _check('month', ~Q(kind__in=MONTHLY) | Q(period_start__day=1)),
            _check('year', ~Q(kind__in=YEARLY) | Q(period_start__day=1, period_start__month=1)),
            _check('site_notice', ~Q(kind__in=SITE_NOTICES) | Q(occurred_on__isnull=False)),
            _check('escape', Q(kind=ReportKind.ESCAPE, escape__isnull=False)
                   | (~Q(kind=ReportKind.ESCAPE) & Q(escape__isnull=True)),
                   _('An escape notice is about an escape, and no other report is.')),
            _check('harvest_condition', Q(harvest_condition='')
                   | Q(kind=ReportKind.BIOMASS, harvest_condition__in=HarvestCondition.values),
                   _('Only the biomass report has a condition of the harvested fish.')),
            _check('no_cleaner_feed', Q(no_cleaner_feed=False) | Q(kind=ReportKind.CLEANER_FISH),
                   _('Only the cleaner-fish report says that no feed was given.')),
            _check('late_when_filed', Q(filed_late__isnull=True, deadline_on__isnull=True) | Q(submitted_at__isnull=False),
                   _('Only a filed report is late or on time.')),
            _check('health_event', Q(kind=ReportKind.DISEASE, health_event__isnull=False)
                   | (~Q(kind=ReportKind.DISEASE) & (Q(kind=ReportKind.WELFARE) | Q(health_event__isnull=True))),
                   _('A disease notice is about a health event; a welfare notice may be; no other report is.')),
            _check('narrative', Q(kind__in=NARRATIVE_KINDS)
                   | Q(what_happened='', found_at__isnull=True, cause='', fish_dead__isnull=True,
                       fish_injured__isnull=True, fish_involved__isnull=True, situation='', measures='')),
            _check('channel', Q(channel='') | Q(channel__in=Channel.values)),
            _check('submission', Q(submitted_at__isnull=True, submitted_by__isnull=True, channel='', reference='')
                   | (Q(submitted_at__isnull=False, submitted_by__isnull=False) & ~Q(channel='')
                      & (~Q(reference='') | Q(channel__in=WITHOUT_REFERENCE))),
                   _('A filing has its time, who recorded it, how it was filed and, unless it was phoned in, its '
                     'receipt or reference.')),
            _check('kept', ~Q(is_deleted=True, submitted_at__isnull=False),
                   _('A filed report is never deleted: start a correction instead.')),
            _check('not_itself', ~Q(corrects=F('pk'))),
            models.UniqueConstraint(
                fields=['kind', 'site', 'facility', 'period_start'], nulls_distinct=False,
                condition=Q(is_deleted=False, corrects__isnull=True, period_start__isnull=False),
                name='uq_regulatory_reports_period',
                violation_error_message=_('This report has already been started for this period: open it from '
                                          'the list.')),
            models.UniqueConstraint(
                fields=['kind', 'site', 'occurred_on'],
                condition=Q(is_deleted=False, corrects__isnull=True, kind__in=SITE_NOTICES),
                name='uq_regulatory_reports_site_notice',
                violation_error_message=_('This notice has already been started: open it from the list.')),
            models.UniqueConstraint(
                fields=['kind', 'health_event'],
                condition=Q(is_deleted=False, corrects__isnull=True, health_event__isnull=False),
                name='uq_regulatory_reports_event_notice',
                violation_error_message=_('This health event has a notice already: open it from the list.')),
            models.UniqueConstraint(
                fields=['kind', 'escape'], condition=Q(is_deleted=False, corrects__isnull=True, escape__isnull=False),
                name='uq_regulatory_reports_escape_notice',
                violation_error_message=_('This escape has a notice already: open it from the list.')),
            models.UniqueConstraint(
                fields=['corrects'], condition=Q(is_deleted=False, corrects__isnull=False),
                name='uq_regulatory_reports_correction',
                violation_error_message=_('This report already has a correction: open it from the list.')),
        ]
        indexes = [models.Index(fields=['kind', 'period_start'])]

    def __str__(self):
        where = self.site or self.facility
        when = self.period.label() if self.period else (self.occurred_on.isoformat() if self.occurred_on else '')
        return ' · '.join(str(part) for part in (self.get_kind_display(), where, when) if part)

    # ---- what it is -----------------------------------------------------------------------------------
    @property
    def info(self):
        return info(self.kind)

    @property
    def days_late(self):
        """How many days after its deadline (in Oslo) it was filed; 0 when it was on time or has no deadline."""
        if not self.filed_late:
            return 0
        return (periods.oslo_today(self.submitted_at) - self.deadline_on).days

    @property
    def period(self):
        """The periods.Period the report is for; None for a notice."""
        if self.period_start is None:
            return None
        return periods.Period(self.info.grain, self.period_start)

    @property
    def deadline(self):
        """The authority's deadline (a date in Oslo); None for a notice, which is filed at once."""
        return self.info.deadline(self.period) if self.period and self.info.deadline else None

    @property
    def is_submitted(self):
        return self.submitted_at is not None

    @property
    def is_superseded(self):
        """A filed correction replaces it (a list annotates it, `has_filed_correction`, to ask once for all)."""
        if hasattr(self, 'has_filed_correction'):
            return self.has_filed_correction
        return self.corrections.filter(submitted_at__isnull=False).exists()

    @property
    def status(self):
        if self.submitted_at is None:
            return 'draft'
        return 'superseded' if self.is_superseded else 'submitted'

    def status_display(self):
        return {'draft': gettext('Draft'), 'submitted': gettext('Filed'),
                'superseded': gettext('Replaced by a correction')}[self.status]

    # ---- the rules the database cannot word ------------------------------------------------------------
    def clean(self):
        super().clean()
        if not self._state.adding:
            stored = type(self).all_objects.filter(pk=self.pk).values('submitted_at').first()
            if stored and stored['submitted_at'] is not None:
                raise ValidationError(gettext('It was filed and cannot change: start a correction instead.'))
        if self.health_event_id and self.site_id and self.health_event.site_id != self.site_id:
            raise ValidationError({'health_event': gettext('Choose a health event of the site.')})
        if self.escape_id and self.site_id:
            unit = self.escape.operation.movements.select_related('unit__production_department').first().unit
            if unit.production_department.site_id != self.site_id:
                raise ValidationError({'escape': gettext('Choose an escape from a unit of the site.')})

    def delete_blockers(self):
        if self.submitted_at is not None:
            return [gettext('It was filed: start a correction instead.')]
        if self.corrections.filter(is_deleted=False).exists():
            return [gettext('A correction of it has been started: discard that first.')]
        return []


class ReportSnapshot(models.Model):
    """What was told to the authority, frozen when the person recorded the filing: the figures as filed, keyed by
    the records they were read from, with codes rather than translated words and decimals as text, the person's
    answers, and the identity (organisation number, lokalitetsnummer, unit numbers, species codes) as they were.
    It is a copy of a filed document, read only to show it, export it again and compare it with what the records
    say now; nothing computes from it (as the activity log's changes are). Append-only (a database trigger); its
    hash is also in the filing's activity-log entry, which is append-only too.

    `sources_fingerprint` is a hash of what the report's source queries returned (each row's id, version and
    deleted flag): a void, a backdated record or a unit moved to another site changes it, so a list can tell which
    filed reports to read again."""

    report = models.OneToOneField(Report, primary_key=True, on_delete=models.PROTECT, related_name='snapshot',
                                  verbose_name=_('Report'))
    format_version = models.PositiveSmallIntegerField(_('Format version'))
    content = models.JSONField(_('Content as filed'))
    content_sha256 = models.CharField(_('Content hash'), max_length=64)
    sources_fingerprint = models.CharField(_('Sources fingerprint'), max_length=64)
    created_at = models.DateTimeField(_('Frozen at'), auto_now_add=True)

    class Meta:
        db_table = 'regulatory_report_snapshots'
        verbose_name = _('filed report content')
        verbose_name_plural = _('filed report contents')
        constraints = [
            models.CheckConstraint(condition=Q(content_sha256__regex=SHA256),
                                   name='chk_regulatory_report_snapshots_sha'),
            models.CheckConstraint(condition=Q(sources_fingerprint__regex=SHA256),
                                   name='chk_regulatory_report_snapshots_fingerprint'),
        ]

    def __str__(self):
        return str(self.report)


class QuestionStatus(models.TextChoices):
    OPEN = 'open', _('Open')
    ANSWERED = 'answered', _('Answered')


class OpenQuestion(AuditedModel):
    """A question only the authority can answer, on which a rule of a report rests (docs/regulatory-reports.md, section 7):
    the owner's work list for Mattilsynet, Fiskeridirektoratet or the county. While it is open the report rule it affects is
    unverified and the pages say so; the answer, who asked and when are kept here."""

    code = models.CharField(_('Number'), max_length=10)
    question = models.CharField(_('Question'), max_length=1000)
    authority = models.CharField(_('Asked of'), max_length=100)
    affects = models.CharField(_('The report rule it affects'), max_length=500)
    status = models.CharField(_('Status'), max_length=10, choices=QuestionStatus.choices, default=QuestionStatus.OPEN)
    asked_by = models.CharField(_('Asked by'), max_length=150, blank=True)
    asked_on = models.DateField(_('Asked on'), null=True, blank=True)
    answer = models.CharField(_('Answer'), max_length=2000, blank=True)
    answered_on = models.DateField(_('Answered on'), null=True, blank=True)

    class Meta:
        db_table = 'regulatory_open_questions'
        ordering = ['code']
        verbose_name = _('open question')
        verbose_name_plural = _('open questions')
        constraints = [
            models.UniqueConstraint(fields=['code'], condition=Q(is_deleted=False), name='uq_open_questions_code_live',
                                    violation_error_message=_('Another question has this number.')),
            models.CheckConstraint(condition=Q(status__in=QuestionStatus.values), name='chk_open_questions_status'),
            models.CheckConstraint(
                condition=Q(status=QuestionStatus.ANSWERED, answer__gt='', answered_on__isnull=False)
                | Q(status=QuestionStatus.OPEN, answered_on__isnull=True),
                name='chk_open_questions_answer',
                violation_error_message=_('An answered question has its answer and the day it came; an open one has '
                                          'no answer day.')),
            models.CheckConstraint(
                condition=Q(asked_on__isnull=True) | Q(answered_on__isnull=True) | Q(answered_on__gte=F('asked_on')),
                name='chk_open_questions_days',
                violation_error_message=_('It was answered on or after the day it was asked.')),
        ]

    def __str__(self):
        return f'{self.code} · {self.question[:60]}'


class DueClosure(models.Model):
    """A report that was owed and will not be filed, closed by a person with the reason (a slaughter that never took place,
    a period filed elsewhere): the due list stops listing it. Reopening deletes the row; both are in the activity log.
    Nothing here is a report and nothing is sent."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kind = models.CharField(_('Report'), max_length=20, choices=ReportKind.choices)
    site = models.ForeignKey(Site, null=True, blank=True, on_delete=models.PROTECT, related_name='+',
                             verbose_name=_('Site'))
    facility = models.ForeignKey(SlaughterFacility, null=True, blank=True, on_delete=models.PROTECT, related_name='+',
                                 verbose_name=_('Slaughter facility'))
    period_start = models.DateField(_('Period'))
    reason = models.CharField(_('Why it is closed'), max_length=500)
    closed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                  related_name='+', verbose_name=_('Closed by'))
    closed_at = models.DateTimeField(_('Closed at'), auto_now_add=True)

    class Meta:
        db_table = 'regulatory_due_closures'
        ordering = ['-closed_at']
        verbose_name = _('closed report')
        verbose_name_plural = _('closed reports')
        constraints = [
            models.CheckConstraint(condition=Q(kind__in=PERIODIC), name='chk_due_closures_kind'),
            models.CheckConstraint(
                condition=Q(kind=ReportKind.SLAUGHTER_PLANNED, facility__isnull=False, site__isnull=True)
                | (~Q(kind=ReportKind.SLAUGHTER_PLANNED) & Q(site__isnull=False, facility__isnull=True)),
                name='chk_due_closures_place'),
            models.CheckConstraint(condition=~Q(reason=''), name='chk_due_closures_reason',
                                   violation_error_message=_('Say why it is closed.')),
            models.UniqueConstraint(fields=['kind', 'site', 'facility', 'period_start'], nulls_distinct=False,
                                    name='uq_due_closures_period',
                                    violation_error_message=_('This report is closed already.')),
        ]

    def __str__(self):
        return f'{self.get_kind_display()} · {self.site or self.facility} · {self.period_start.isoformat()}'


# ---- the answers no record holds (row lists of a report) --------------------------------------------------
class LiceSubstance(models.TextChoices):
    """The substances of Mattilsynet's lice report a resistance or a sensitivity test is about (its `resistens`
    list, the reporting API's OpenAPI read 2026-11-03), stored as the official value."""
    AZAMETHIPHOS = 'AZAMETHIPHOS', _('Azamethiphos')
    CYPERMETHRIN = 'CYPERMETHRIN', _('Cypermethrin')
    DELTAMETHRIN = 'DELTAMETHRIN', _('Deltamethrin')
    IMIDACLOPRID = 'IMIDAKLOPRID', _('Imidacloprid')
    HYDROGEN_PEROXIDE = 'HYDROGENPEROKSID', _('Hydrogen peroxide')
    DIFLUBENZURON = 'DIFLUBENZURON', _('Diflubenzuron')
    EMAMECTIN_BENZOATE = 'EMAMECTIN_BENZOAT', _('Emamectin benzoate')
    TEFLUBENZURON = 'TEFLUBENZURON', _('Teflubenzuron')
    FRESHWATER = 'FERSKVANNSBEHANDLING', _('Freshwater treatment')
    OTHER = 'ANNEN_RESISTENS', _('Other')


class SuspicionCause(models.TextChoices):
    BIOASSAY = 'BIOESSAY', _('A bioassay')
    REDUCED_EFFECT = 'NEDSATT_BEHANDLINGSEFFEKT', _('Reduced effect of a treatment')
    AREA = 'SITUASJONEN_I_OMRÅDET', _('The situation in the area')
    OTHER = 'ANNEN_ÅRSAK', _('Other')


class TestResult(models.TextChoices):
    SENSITIVE = 'FØLSOM', _('Sensitive')
    REDUCED = 'NEDSATT_FØLSOMHET', _('Reduced sensitivity')
    RESISTANT = 'RESISTENS', _('Resistant')


class ReportRow(models.Model):
    """A row a report owns, edited as a list on the report's form (core.crud.RowList) while it is a draft; a database
    trigger refuses any change once the report is filed."""

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name='+', verbose_name=_('Created by'))
    created_at = models.DateTimeField(_('Created at'), auto_now_add=True)

    class Meta:
        abstract = True


class ResistanceSuspicion(ReportRow):
    """A suspicion of resistance to a lice treatment reported for the week (lakselusforskriften § 10 e)."""

    report = models.ForeignKey(Report, on_delete=models.CASCADE, related_name='resistance_suspicions',
                               verbose_name=_('Report'))
    substance = models.CharField(_('Resistance to'), max_length=30, choices=LiceSubstance.choices)
    other_substance = models.CharField(_('Other: which'), max_length=255, blank=True)
    cause = models.CharField(_('Suspected because of'), max_length=30, choices=SuspicionCause.choices)
    other_cause = models.CharField(_('Other: why'), max_length=255, blank=True)

    class Meta:
        db_table = 'regulatory_report_resistance_suspicions'
        ordering = ['created_at', 'id']
        verbose_name = _('resistance suspicion')
        verbose_name_plural = _('resistance suspicions')
        constraints = [
            models.CheckConstraint(condition=Q(substance__in=LiceSubstance.values),
                                   name='chk_resistance_suspicions_substance'),
            models.CheckConstraint(condition=Q(cause__in=SuspicionCause.values), name='chk_resistance_suspicions_cause'),
            models.CheckConstraint(
                condition=Q(substance=LiceSubstance.OTHER, other_substance__gt='')
                | (~Q(substance=LiceSubstance.OTHER) & Q(other_substance='')),
                name='chk_resistance_suspicions_other_substance',
                violation_error_message=_('Say which substance when it is another one, and only then.')),
            models.CheckConstraint(
                condition=Q(cause=SuspicionCause.OTHER, other_cause__gt='')
                | (~Q(cause=SuspicionCause.OTHER) & Q(other_cause='')),
                name='chk_resistance_suspicions_other_cause',
                violation_error_message=_('Say why when it is another reason, and only then.')),
        ]

    def __str__(self):
        return f'{self.get_substance_display()} · {self.get_cause_display()}'


class SensitivityTest(ReportRow):
    """A sensitivity test's result reported for the week (lakselusforskriften § 10 d). A lab result is a health fact:
    it moves to the health records once they have lab results, and the report then reads it
    (docs/regulatory-reports.md, 5.1)."""

    report = models.ForeignKey(Report, on_delete=models.CASCADE, related_name='sensitivity_tests',
                               verbose_name=_('Report'))
    tested_on = models.DateField(_('Tested on'))
    laboratory = models.CharField(_('Laboratory'), max_length=255)
    substance = models.CharField(_('Substance'), max_length=30, choices=LiceSubstance.choices)
    other_substance = models.CharField(_('Other: which'), max_length=255, blank=True)
    result = models.CharField(_('Result'), max_length=20, choices=TestResult.choices)

    class Meta:
        db_table = 'regulatory_report_sensitivity_tests'
        ordering = ['tested_on', 'id']
        verbose_name = _('sensitivity test')
        verbose_name_plural = _('sensitivity tests')
        constraints = [
            models.CheckConstraint(condition=Q(substance__in=LiceSubstance.values),
                                   name='chk_sensitivity_tests_substance'),
            models.CheckConstraint(condition=Q(result__in=TestResult.values), name='chk_sensitivity_tests_result'),
            models.CheckConstraint(
                condition=Q(substance=LiceSubstance.OTHER, other_substance__gt='')
                | (~Q(substance=LiceSubstance.OTHER) & Q(other_substance='')),
                name='chk_sensitivity_tests_other_substance',
                violation_error_message=_('Say which substance when it is another one, and only then.')),
        ]

    def __str__(self):
        return f'{self.tested_on.isoformat()} · {self.laboratory} · {self.get_substance_display()}'


class TreatmentAnswer(ReportRow):
    """What a sea-lice treatment's record does not say, for the week's report: whether it was given before the count
    (the records carry dates, no times, so a treatment that ended on the day of a count cannot be told) and which
    treatments were given together (the same combination number)."""

    report = models.ForeignKey(Report, on_delete=models.CASCADE, related_name='treatment_answers',
                               verbose_name=_('Report'))
    treatment = models.ForeignKey(Treatment, on_delete=models.PROTECT, related_name='+', verbose_name=_('Treatment'))
    done_before_count = models.BooleanField(_('Given before the count'), default=False)
    combination = models.PositiveSmallIntegerField(_('Given together with others, combination'), null=True,
                                                   blank=True)

    class Meta:
        db_table = 'regulatory_report_treatment_answers'
        ordering = ['treatment__start_date', 'id']
        verbose_name = _('treatment answer')
        verbose_name_plural = _('treatment answers')
        constraints = [
            models.UniqueConstraint(fields=['report', 'treatment'], name='uq_treatment_answers_treatment',
                                    violation_error_message=_('Each treatment can be listed once.')),
            models.CheckConstraint(condition=Q(combination__isnull=True) | Q(combination__gte=1, combination__lte=9),
                                   name='chk_treatment_answers_combination',
                                   violation_error_message=_('A combination is numbered 1 to 9.')),
        ]

    def __str__(self):
        return str(self.treatment)


class UnitAnswer(ReportRow):
    """A production unit used for production of reduced capacity that month (akvakulturdriftsforskriften § 44 first
    paragraph j): the one item of the monthly biomass report no record holds."""

    report = models.ForeignKey(Report, on_delete=models.CASCADE, related_name='unit_answers',
                               verbose_name=_('Report'))
    unit = models.ForeignKey(Tank, on_delete=models.PROTECT, related_name='+', verbose_name=_('Unit'))
    reduced_capacity = models.BooleanField(_('Used for production of reduced capacity'), default=False)

    class Meta:
        db_table = 'regulatory_report_unit_answers'
        ordering = ['unit__code', 'id']
        verbose_name = _('unit answer')
        verbose_name_plural = _('unit answers')
        constraints = [
            models.UniqueConstraint(fields=['report', 'unit'], name='uq_unit_answers_unit',
                                    violation_error_message=_('Each unit can be listed once.')),
        ]

    def __str__(self):
        return f'{self.unit.code} · {gettext("reduced capacity") if self.reduced_capacity else "-"}'

