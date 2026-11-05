"""The duties the authorities put on a farm that are not a report of this system (coverage review R16, R17, R23, R25, R15, R29, R31).

Nothing here is a report kind and nothing is built to file them: each is listed with what the saved official text says (its deadline,
its channel, whom it binds by production form, where it is written) and what is not known (marked unverified, with the question of
the register it rests on). The two that fall due on 1 October each year for a sea site, the driftsplan and the lice coordination plan,
are also listed as due lines (`due.DueList.duties`) with the person's own record that they were done (`OutsideDutyDone`: when and
the reference). The rest are on the page of duties outside this system (Production › Reports › Duties outside this system)."""
from dataclasses import dataclass, field
from datetime import date

from django.utils.translation import gettext_lazy as _

from farm.models import Site

from .models import OutsideDuty

FIRST_YEAR = 2026                 # the first 1 October the saved official texts name
SEA = Site.Type.SEA_CAGE
FORM = Site.ProductionForm


@dataclass(frozen=True)
class Duty:
    code: str
    title: object
    deadline: object                # what the official text says, in words
    channel: object
    basis: object                   # the regulation or page it is written in
    source: str                     # where to read it ('' when no page was saved)
    binds: dict = field(default_factory=dict)          # production form -> whom it binds, in words
    unverified: object = ''         # what is not known, and the question of the register it rests on
    recordable: bool = False        # an annual duty a person records as done here (OutsideDuty)


DUTIES = (
    Duty(OutsideDuty.DRIFTSPLAN, _('Operating plan (driftsplan)'),
         _('1 October each year, for the two next calendar years (the saved page: "Fristen for å sende inn driftsplan for 2027 '
           'og 2028 er 1. oktober 2026")'),
         _('Mattilsynet’s new solution in Altinn 3; the reporting API also has an endpoint for it (not on the entry page)'),
         _('Mattilsynet: "Slik sender du inn driftsplan i Mattilsynets nye løsning" (reviewed 2026-09-18)'),
         'https://info.altinn.no/skjemaoversikt/mattilsynet/driftsplan-for-akvakulturanlegg-med-stamfisk-og-matfisk-i-sjoe/',
         {FORM.MATFISK: _('every sea site that produces food fish: also a site not to be in use in the period'),
          FORM.STAMFISK: _('every sea site that produces broodstock: also a site not to be in use in the period'),
          FORM.SETTEFISK: _('not named: a juvenile site is not a "matfisk or stamfisk" site'),
          'other': _('not named: research and other production is not food fish or broodstock')},
         _('The consequence of filing late, and whether the API is allowed for it, are unverified (Q6). A plan is updated when '
           'the fallowing or a move changes by more than a month, a move by more than 100 000 fish, a stocking by more than a '
           'month or 10 %, a planned move or stocking is not made, cleaner fish go to another site, or the production '
           'technology changes.'),
         recordable=True),
    Duty(OutsideDuty.LICE_PLAN, _('Lice coordination plan (lakselusforskriften § 4)'),
         _('"oversendes årlig til Mattilsynet innen 1. oktober"; changes of the plan are notified at once'),
         _('Not stated in the text saved; unverified (Q6)'),
         _('Lakselusforskriften § 4'),
         'https://lovdata.no/forskrift/2012-12-05-1140/§4',
         {FORM.MATFISK: _('a sea site with salmonids'), FORM.STAMFISK: _('a sea site with salmonids'),
          FORM.SETTEFISK: _('a sea site with salmonids (the duty follows the fish, not the production form)'),
          'other': _('a sea site with salmonids')},
         _('The channel and the consequence of filing late are unverified (Q6).'),
         recordable=True),
    Duty('broodstock_year', _('Yearly report of broodstock on land (akvakulturdriftsforskriften § 45)'),
         _('15 July each year, for 1 June to 31 May, by year class'),
         _('To Fiskeridirektoratet; the form is not saved'),
         _('Akvakulturdriftsforskriften § 45'), 'https://lovdata.no/forskrift/2008-06-17-822/§45',
         {FORM.STAMFISK: _('a land site with broodstock of salmon, trout, rainbow trout or cleaner fish'),
          FORM.MATFISK: _('only if it keeps broodstock of those species on land'),
          FORM.SETTEFISK: _('only if it keeps broodstock of those species on land'),
          'other': _('only if it keeps broodstock of those species on land')},
         _('Not built. The form and the channel are unverified.')),
    Duty('recapture', _('Recapture after an escape (akvakulturdriftsforskriften § 39 third paragraph)'),
         _('When a recapture starts and when it ends'),
         _('Not saved; unverified'), _('Akvakulturdriftsforskriften § 39'),
         'https://lovdata.no/forskrift/2008-06-17-822/§39',
         {FORM.MATFISK: _('every site where fish escape'), FORM.STAMFISK: _('every site where fish escape'),
          FORM.SETTEFISK: _('every site where fish escape'), 'other': _('every site where fish escape')},
         _('Not built: no notice kind for the start and end of a recapture. The escape notice (Escape tab) is the report.')),
    Duty('executed_slaughter', _('Executed slaughter'),
         _('The 7th of the following month, for every slaughter week'),
         _('POST /api/slakt/v1/utfort, or the Altinn form "Gjennomført slakting av oppdrettsfisk"'),
         _('Restkontrollforskriften; Mattilsynet: slaughter of fish'),
         'https://www.mattilsynet.no/fisk-og-akvakultur/slakting-av-fisk',
         {FORM.MATFISK: _('filed by the slaughterhouse or packing plant: a farm owes it only when it runs its own'),
          FORM.STAMFISK: _('as for food fish'), FORM.SETTEFISK: _('not named'), 'other': _('not named')},
         _('Not built (decision D-3): the system holds no gutted kilos per quality class. A farm selling to a third-party '
           'slaughterhouse does not owe it; Q5 asks whether a farm may report the planned slaughter.')),
    Duty('county_report', _('Yearly report to the county governor (Statsforvalteren)'),
         _('One county names 1 March of the next year, by e-mail (Møre og Romsdal, 2027)'),
         _('E-mail to the county governor; unverified for other counties'),
         _('The discharge permit of a land site'), '',
         {FORM.MATFISK: _('a land site with a discharge permit'), FORM.STAMFISK: _('a land site with a discharge permit'),
          FORM.SETTEFISK: _('a land site with a discharge permit'), 'other': _('a land site with a discharge permit')},
         _('Whether it applies to the permit and county of the farm is unknown (Q9). Not built.')),
    Duty('cleaner_broodstock', _('Yearly report of cleaner-fish broodstock'),
         _('Not found'), _('Not found'), _('Mattilsynet: guide on cleaner fish ("årlig rapportering om stamfisk av rensefisk")'),
         'https://www.mattilsynet.no/fisk-og-akvakultur/rensefisk',
         {FORM.STAMFISK: _('a site with cleaner-fish broodstock'), FORM.MATFISK: _('not named'),
          FORM.SETTEFISK: _('a site with cleaner-fish broodstock'), 'other': _('a site with cleaner-fish broodstock')},
         _('Form, deadline and channel are unverified (Q8). Not built.')),
)
BY_CODE = {duty.code: duty for duty in DUTIES}


def applies(duty, site, salmonids):
    """(applies, why not) for a recordable annual duty at a site: the driftsplan binds a sea site of food fish or broodstock, the lice
    plan a sea site with salmonids (`salmonids`: whether it has ever held some)."""
    if site.type != SEA:
        return False, _('%(site)s is not a sea site') % {'site': site.name}
    if duty.code == OutsideDuty.DRIFTSPLAN:
        if not site.production_form:
            return False, _('site not set up: no production form')
        if site.production_form not in (FORM.MATFISK, FORM.STAMFISK):
            return False, _('only a sea site of food fish or broodstock has a driftsplan')
        return True, ''
    if not salmonids:
        return False, _('no salmonids have been held at %(site)s') % {'site': site.name}
    return True, ''


@dataclass(frozen=True)
class DutyLine:
    """Where an annual duty outside the system stands for a site and a year: done (with the person's record), overdue, due within 60
    days, or upcoming."""
    duty: Duty
    site: object
    year: int
    deadline: date
    status: str
    done: object = None


DONE, OVERDUE, DUE_SOON, UPCOMING = 'done', 'overdue', 'due_soon', 'upcoming'
SOON_DAYS = 60


def lines_of(site, today, records, salmonids):
    """The lines of the annual duties that bind `site`, from the first 1 October the texts name to this year's."""
    found = []
    for duty in DUTIES:
        if not duty.recordable or not applies(duty, site, salmonids)[0]:
            continue
        for year in range(FIRST_YEAR, today.year + 1):
            deadline = date(year, 10, 1)
            done = records.get((duty.code, site.pk, year))
            if done is not None:
                status = DONE
            elif today > deadline:
                status = OVERDUE
            elif (deadline - today).days <= SOON_DAYS:
                status = DUE_SOON
            else:
                status = UPCOMING
            found.append(DutyLine(duty, site, year, deadline, status, done))
    return found
