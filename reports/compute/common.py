"""What every report's computation shares: the result it returns, the identity the authority knows a site and a
unit by, how numbers are written into the content, and the fingerprint of the rows read.

A computation reads the records through the farm's own reads (farm/stock/read.py, farm/feeding/read.py) and never
recomputes a stock figure its own way. It returns the content (JSON-ready: codes and ids, never translated words;
decimals as text), what keeps it from being ready (problems) and what the person should know (warnings), both in the
reader's language and never frozen, and the scope it read, for the fingerprint."""
import hashlib
import json
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from django.utils.translation import gettext as _

FORMAT_VERSION = 1


@dataclass
class Result:
    """A report's computation: `content` is what is filed (and frozen when it is); `problems` keep it from being
    ready; `warnings` are worth a look; `scope` is [(label, queryset of rows read)] for the fingerprint."""
    content: dict
    problems: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    scope: list = field(default_factory=list)

    @property
    def ready(self):
        return not self.problems


def note(problems, message):
    """Adds a problem or a warning once: a species without a code is named once, not once per unit."""
    if message not in problems:
        problems.append(message)


def text(value, places):
    """A decimal as the content keeps it: text with `places` decimals (half up), so it compares exactly; None stays
    None."""
    if value is None:
        return None
    return str(Decimal(value).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP))


def whole(value):
    """A number as a whole number (the authorities' kilos are integers), half up; None stays None."""
    if value is None:
        return None
    return int(Decimal(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def unit_number(unit):
    """The unit's number in the reports: its regulatory unit ID, else its code (the authority asks that it matches
    the operations journal)."""
    return unit.regulatory_unit_id or unit.code


def identity(site, problems):
    """The site as the authority knows it; what is missing goes into `problems`."""
    organisation = site.organisation_number      # nine digits or empty: the database holds it
    if not organisation:
        note(problems, _('%(site)s has no organisation number (Facility › Sites, its Reports tab).') % {'site': site})
    if site.lokalitetsnummer is None:
        note(problems, _('%(site)s has no lokalitetsnummer (Facility › Sites).') % {'site': site})
    return {'organisation_number': organisation or None, 'lokalitetsnummer': site.lokalitetsnummer,
            'site': site.name, 'site_code': site.code}


def species_code(species, problems):
    """A species' official code (FAO ASFIS, as the reports ask); missing goes into `problems`."""
    if not species.official_code:
        note(problems, _('%(species)s has no official code (Setup › Reference data › Species).') % {
            'species': species})
    return species.official_code or None


def year_class(batch, problems):
    """The batch's year class (D-14: entered per batch, no default); missing goes into `problems`, once per batch."""
    found = getattr(batch, 'year_class', None)
    if found is None:
        note(problems, _('Batch %(batch)s has no year class (Operations › Production units).') % {'batch': batch.code})
    return found


def fingerprint(scope):
    """A hash of what the scope's querysets return now: each row's id, version and deleted flag where it has them.
    Re-run on read, it changes when a row the report read is voided, edited or added (a backdated record), or when
    a unit moves (OUR-05)."""
    digest = hashlib.sha256()
    for label, rows in scope:
        names = [name for name in ('id', 'version', 'is_deleted') if _has(rows.model, name)]
        for row in sorted(rows.values_list(*names), key=str):
            digest.update(f'{label}:{row}\n'.encode())
    return digest.hexdigest()


def _has(model, name):
    return any(field.attname == name or field.name == name for field in model._meta.concrete_fields)


def content_hash(content):
    """The content's SHA-256, over its JSON with sorted keys: the hash the filing's log entry carries."""
    return hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def flatten(value, path=''):
    """{path: leaf} of a content, for comparing two: dicts by key, lists by position."""
    if isinstance(value, dict):
        found = {}
        for key, item in value.items():
            found.update(flatten(item, f'{path}/{key}'))
        return found
    if isinstance(value, list):
        found = {}
        for index, item in enumerate(value):
            found.update(flatten(item, f'{path}/{index}'))
        return found if value else {path: []}
    return {path: value}
