"""The reports a farm owes the Norwegian authorities: who gets each, on what basis, for what period, by when, and
how a person files it. One place, read by the due list, the pages and the exports (docs/regulatory-reports.md,
section 1, read on lovdata.no, Mattilsynet's reporting API and Altinn's form pages on 2026-11-03)."""
from dataclasses import dataclass

from django.db import models
from django.utils.translation import gettext_lazy as _

from . import periods


class ReportKind(models.TextChoices):
    SEA_LICE = 'sea_lice', _('Sea lice')
    SMOLT = 'smolt', _('Smolt')
    CLEANER_FISH = 'cleaner_fish', _('Cleaner fish')
    BIOMASS = 'biomass', _('Monthly biomass')
    LAND_STOCK = 'land_stock', _('Yearly stock of a land site')
    SITE_IN_USE = 'site_in_use', _('Site taken into use')
    SITE_EMPTIED = 'site_emptied', _('Site emptied')
    SLAUGHTER_PLANNED = 'slaughter_planned', _('Planned slaughter')
    ESCAPE = 'escape', _('Escape')
    DISEASE = 'disease', _('Disease')
    WELFARE = 'welfare', _('Welfare event')


EVENT = 'event'
SITE, FACILITY = 'site', 'facility'


@dataclass(frozen=True)
class KindInfo:
    authority: str          # who receives it
    basis: str              # the regulation, as the authority cites it
    grain: str              # periods.WEEK, MONTH, YEAR or EVENT
    scope: str              # SITE or FACILITY
    channel: str            # where a person files it
    deadline: object = None  # period -> the deadline date; None for an event ("at once")
    deadline_text: str = ''


MATTILSYNET, FISKERIDIREKTORATET = 'Mattilsynet', 'Fiskeridirektoratet'

KINDS = {
    ReportKind.SEA_LICE: KindInfo(
        MATTILSYNET, 'lakselusforskriften § 10', periods.WEEK, SITE,
        _('Altinn: “Ukentlig rapportering av lakselus”, or Mattilsynet’s reporting API'),
        periods.tuesday_after, _('Tuesday of the next week')),
    ReportKind.SMOLT: KindInfo(
        MATTILSYNET, 'akvakulturdriftsforskriften § 58', periods.MONTH, SITE,
        _('Altinn: “Månedsrapport settefisk”, or Mattilsynet’s reporting API'),
        periods.seventh_after, _('the 7th of the next month')),
    ReportKind.CLEANER_FISH: KindInfo(
        MATTILSYNET, 'akvakulturdriftsforskriften § 44 jf. § 3 første ledd bokstav h', periods.MONTH, SITE,
        _('Altinn: “Månedlig rapportering for bruk av rensefisk”, or Mattilsynet’s reporting API'),
        periods.seventh_after, _('the 7th of the next month')),
    ReportKind.BIOMASS: KindInfo(
        FISKERIDIREKTORATET, 'akvakulturdriftsforskriften § 44', periods.MONTH, SITE,
        _('Fiskeridirektoratet’s monthly biomass report in Altinn; confirm the form with Fiskeridirektoratet'),
        periods.seventh_after, _('the 7th of the next month')),
    ReportKind.LAND_STOCK: KindInfo(
        FISKERIDIREKTORATET, 'akvakulturdriftsforskriften § 44a', periods.YEAR, SITE,
        _('Fiskeridirektoratet; confirm the form with Fiskeridirektoratet'),
        periods.seventh_after, _('7 January')),
    ReportKind.SITE_IN_USE: KindInfo(
        FISKERIDIREKTORATET, 'akvakulturdriftsforskriften § 44a', EVENT, SITE,
        _('Fiskeridirektoratet; confirm the form with Fiskeridirektoratet'), None, _('when it happens')),
    ReportKind.SITE_EMPTIED: KindInfo(
        FISKERIDIREKTORATET, 'akvakulturdriftsforskriften § 44a', EVENT, SITE,
        _('Fiskeridirektoratet; confirm the form with Fiskeridirektoratet'), None, _('when it happens')),
    ReportKind.SLAUGHTER_PLANNED: KindInfo(
        MATTILSYNET, 'restkontrollforskriften § 9a', periods.WEEK, FACILITY,
        _('Altinn: “Planlagt slakting av oppdrettsfisk” (filed by the slaughterhouse), or Mattilsynet’s reporting '
          'API'),
        periods.thursday_before, _('Thursday 24:00 of the week before, or when the fish start fasting if earlier')),
    ReportKind.ESCAPE: KindInfo(
        FISKERIDIREKTORATET, 'akvakulturdriftsforskriften § 38', EVENT, SITE,
        _('Altinn: “Rømt oppdrettsfisk eller avvik” (the form on fiskeridir.no)'), None, _('at once')),
    ReportKind.DISEASE: KindInfo(
        MATTILSYNET, 'dyrehelseforskriften § 7', EVENT, SITE,
        _('Altinn: “Varsel om velferdshendelse og listeført sykdom på oppdrettsfisk”'), None, _('at once')),
    ReportKind.WELFARE: KindInfo(
        MATTILSYNET, 'akvakulturdriftsforskriften § 14', EVENT, SITE,
        _('Altinn: “Varsel om velferdshendelse og listeført sykdom på oppdrettsfisk”; e-mail to '
          'varsling.akvakultur@mattilsynet.no for an event during transport or at a slaughterhouse'),
        None, _('at once')),
}

PERIODIC = tuple(kind for kind, info in KINDS.items() if info.grain != EVENT)
EVENTS = tuple(kind for kind, info in KINDS.items() if info.grain == EVENT)
BY_FACILITY = tuple(kind for kind, info in KINDS.items() if info.scope == FACILITY)


def info(kind):
    return KINDS[ReportKind(kind)]
