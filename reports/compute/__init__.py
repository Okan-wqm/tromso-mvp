"""Each kind of report's computation from the farm's records (one module per kind) and the one entry point the pages,
the exports, the filing and the "still matches?" check all call, so they cannot disagree."""
from django.utils.translation import gettext as _

from ..kinds import ReportKind
from . import biomass, cleaner, lice, notices, slaughter, smolt
from .common import FORMAT_VERSION, Result, content_hash, fingerprint, flatten  # noqa: F401

# The kinds whose computation is built; a report of another kind cannot be started yet.
COMPUTE = {
    ReportKind.SEA_LICE: lambda report: lice.compute(report.site, report.period, report),
    ReportKind.SMOLT: lambda report: smolt.compute(report.site, report.period),
    ReportKind.CLEANER_FISH: lambda report: cleaner.compute(report.site, report.period),
    ReportKind.BIOMASS: lambda report: biomass.compute(report.site, report.period, report),
    ReportKind.SLAUGHTER_PLANNED: lambda report: slaughter.compute(report.facility, report.period),
    ReportKind.LAND_STOCK: notices.land_stock,
    ReportKind.SITE_IN_USE: notices.site_change,
    ReportKind.SITE_EMPTIED: notices.site_change,
    ReportKind.WELFARE: notices.event,
}


def compute(report):
    """The report's Result as the records give it now, with the contact person the authority can ask (every report
    names one, Mattilsynet's `kontaktperson`)."""
    result = COMPUTE[report.kind](report)
    result.content['contact'] = {'name': report.contact_name, 'email': report.contact_email,
                                 'phone': report.contact_phone}
    if not all(value.strip() for value in result.content['contact'].values()):
        result.problems.append(_('Give the contact person’s name, e-mail and telephone (the Contact person tab).'))
    return result


def deadline(report):
    """The report's deadline: the rule's, and for a planned slaughter the day its fish start fasting when earlier."""
    rule = report.deadline
    if rule is not None and report.kind == ReportKind.SLAUGHTER_PLANNED:
        return slaughter.deadline(report.facility, report.period, rule)
    return rule
