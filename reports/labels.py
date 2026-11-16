"""The one label registry of a report's content (reports/compute): every key the computation writes, named as the report
pages name it, translated (reports/tests/test_labels.py reads the computation's code, so a new key cannot slip by). Both
the report page (`outline`: the figures of a kind without a table of its own, sea lice and cleaner fish) and a filed
report's differences (`describe`: "Unit K-02 · Fish at the month’s end") read it, so no page shows a content or API key;
a number is said as the person's language writes it."""
import re
from decimal import Decimal, InvalidOperation

from django.utils import formats, timezone
from django.utils.translation import gettext, gettext_lazy as _, pgettext_lazy

from core.dates import company_zone, read_day, stored_moment

# A key of the content: the words the report pages give it (the same msgids where a page already names it).
FIELDS = {
    'adjusted': _('Adjusted'),
    'adjusted_down': _('Adjusted down'),
    'adjusted_up': _('Adjusted up'),
    'adult_females': _('Adult females per fish'),
    'amount': _('Amount'),
    'approval_number': _('Approval number'),
    'attached': _('Attached per fish'),
    'average': _('Average'),
    'avg_weight_g': _('Average weight (g)'),
    'basis': _('Basis'),
    'batch': _('Batch'),
    'before_count': _('Done before the count'),
    'biomass_kg': _('Biomass (kg)'),
    'cages': _('Cages'),
    'cause': _('Cause'),
    'closing': _('Closing'),
    'combination': _('Combination'),
    'condition': _('Condition'),
    'confirmation': _('Confirmation'),
    'contact': _('Contact person'),
    'count': _('Count'),
    'counts': _('Lice counts'),
    'culled': _('Culled'),
    'date': _('Date'),
    'days': _('Days'),
    'deaths': _('Deaths'),
    'description': _('Description'),
    'diagnosis': _('Diagnosis'),
    'died': _('Died'),
    'down': _('Down'),
    'dry_kg': _('Dry feed (kg)'),
    'email': _('Email'),
    'escape': _('Escape'),
    'end': _('End'),
    'facility': _('Slaughter facility'),
    'fallow_since': _('Fallow since'),
    'feed': _('Feed'),
    'feed_type': _('Feed type'),
    'feeds': _('Feeds'),
    'fish': _('Fish'),
    'fish_at_end': _('Fish at the month’s end'),
    'fish_dead': _('Fish dead'),
    'fish_injured': _('Fish injured'),
    'fish_involved': _('Fish involved'),
    'form': _('Form'),
    'found_at': _('Found at'),
    'found_time': _('Time found'),
    'from_lokalitetsnummer': _('From lokalitetsnummer'),
    'grams': _('Grams'),
    'harvested': _('Harvested'),
    'health_event': _('Health event'),
    'health_status': _('Health status'),
    'id': _('Reference'),
    'items': _('Items'),
    'kg': _('kg'),
    'kind': _('Kind'),
    'laboratory': _('Laboratory'),
    'last': _('Last'),
    'least': _('Least'),
    'limit': _('Limit'),
    'lines': _('Records read'),
    'lokalitetsnummer': _('Lokalitetsnummer'),
    'losses': _('Lost'),
    'measured_avg_g': _('Measured average weight (g)'),
    'measured_on': _('Measured on'),
    'measures': _('Measures taken'),
    'medicinal': _('Medicinal'),
    'medicine': _('Medicine'),
    'method': _('Method'),
    'mobile': _('Mobile per fish'),
    'moved_in': _('Moved in'),
    'moved_out': _('Moved to another site'),
    'moved_out_of_site': _('Moved out of the site'),
    'name': _('Name'),
    'net': _('Net'),
    'number': _('Unit number'),
    'occurred_on': _('Happened on'),
    'opening': _('Opening'),
    'organisation_number': _('Organisation number'),
    'origin': _('Origin'),
    'other': _('Other'),
    'other_cause': _('Other cause'),
    'other_substance': _('Other substance'),
    'period': _('Period'),
    'phone': _('Phone'),
    'reason': _('Reason'),
    'recaptured': _('Recaptured'),
    'reduced_capacity': _('Reduced capacity'),
    'resistance_suspicions': _('Resistance suspicions'),
    'result': _('Result'),
    'samples': _('Samples'),
    'sensitivity_tests': _('Sensitivity tests'),
    'site': _('Site'),
    'site_code': _('Site code'),
    'situation': _('The situation now'),
    'slaughter_weight_kg': _('Slaughter weight (kg)'),
    'species': pgettext_lazy('singular', 'Species'),
    'start': _('Start'),
    'stock': _('Stock at the month’s end'),
    'stocked': _('Stocked'),
    'strength': _('Strength'),
    'substance': _('Active substance'),
    'suspected': _('Suspected'),
    'temperature_c': _('Sea temperature (°C)'),
    'tested_on': _('Tested on'),
    'to_lokalitetsnummer': _('To lokalitetsnummer'),
    'treatment': _('Treatment'),
    'treatments': _('Treatments'),
    'type': _('Type'),
    'unaccounted': _('Unaccounted for'),
    'unit': _('Unit'),
    'value': _('Value'),
    'volume_m3': _('Volume (m³)'),
    'week': _('Week'),
    'wet_kg': _('Wet feed (kg)'),
    'what_happened': _('What happened'),
    'whole_site': _('Whole site'),
    'year_class': _('Year class'),
}
# A key whose children are records named by their own number or name.
RECORDS = {'units': _('Unit %(name)s'), 'localities': _('Site %(name)s')}
# The same keys when they hold a plain list (a health event's units by number): the list's own words.
GROUPS = {'units': _('Units'), 'localities': _('Sites')}
# The days of a week the planned slaughter gives its kilos by (reports/compute/slaughter.py WEEKDAYS).
FIELDS.update({'monday': _('Monday'), 'tuesday': _('Tuesday'), 'wednesday': _('Wednesday'), 'thursday': _('Thursday'),
               'friday': _('Friday'), 'saturday': _('Saturday'), 'sunday': _('Sunday')})
# A key that only groups (the identity is said apart on the page, as "Identity").
SILENT = {'identity'}
# Keys the computation writes that are not content (a wrapper of its own reading).
NOT_CONTENT = {'content'}
# What the page's own heading already says, left out of the figures.
HEADED = {'kind', 'period', 'identity'}
# Coded values the computation writes, said in words: a batch's biomass basis (reports/compute/biomass.py) and a loss's
# cause. Free text (an escape's cause, a notice's narrative) is the person's own and shown as written.
CODES = {
    'method': {'book': _('Last weighing'), 'projected': _('Projected from the feeding since the last weighing'),
               'book_stale': _('Last weighing, none recent')},
    'loss_cause': {'dead': _('Dead'), 'escape': _('Escape'), 'counting_error': _('Counting error'), 'other': _('Other')},
}


def codes_for(parts):
    """The words of the coded values at a content path, if it holds them."""
    if parts and parts[-1] == 'method':
        return CODES['method']
    if len(parts) > 1 and parts[-1] == 'cause' and 'losses' in parts:
        return CODES['loss_cause']
    return None
UNNAMED = _('(unnamed figure)')
ISO_DAY = re.compile(r'^[0-9]{4}-[0-9]{2}-[0-9]{2}$')
RECORD_ID = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')


def _child(node, key):
    if isinstance(node, dict):
        return node.get(key)
    if isinstance(node, list) and key.isdigit() and int(key) < len(node):
        return node[int(key)]
    return None


def _name(record, key):
    if isinstance(record, dict):
        for field in ('number', 'name', 'site', 'code'):
            if record.get(field):
                return str(record[field])
    elif isinstance(record, (str, int)) and not isinstance(record, bool) and str(record):
        return str(record)                              # a plain list of numbers names each by itself
    return key


def _words(parts, content):
    words, node, parent = [], content, None
    for index, part in enumerate(parts):
        child, last = _child(node, part), index == len(parts) - 1
        if parent in RECORDS:
            words.append(str(RECORDS[parent] % {'name': _name(child, part)}))
        elif isinstance(node, list):
            words.append(f'#{int(part) + 1}' if part.isdigit() else part)
        elif part in FIELDS:
            words.append(str(FIELDS[part]))
        elif part in RECORDS and last:
            words.append(str(GROUPS[part]))                       # the list itself, shown as one row
        elif part not in SILENT and part not in RECORDS:
            words.append(str(UNNAMED) if last else part)          # a key of data (a code, a day) names itself
        node, parent = child, part
    return ' · '.join(words)


def describe(path, *contents):
    """The words for `path`, read in the first of `contents` that has it (what was filed, else what the records give now)."""
    parts = [part for part in path.strip('/').split('/') if part]
    content = next((item for item in contents if _reaches(item, parts)), contents[0] if contents else {})
    return _words(parts, content)


def _reaches(content, parts):
    node = content
    for part in parts[:-1]:
        node = _child(node, part)
        if node is None:
            return False
    return True


# The leaves of a content that name rather than count: an identifier, a code, a year. A change of one of
# IDENTITY_LEAVES is "identity changed since filing" (reports/services.py); every naming leaf (`names`) is printed as it
# is written, never as a number of the language (flow fault M-13: "Organisation number 987,654,321").
IDENTITY_LEAVES = ('/number', '/species', '/organisation_number', '/lokalitetsnummer', '/site', '/site_code')
NAMING_KEYS = frozenset({'number', 'organisation_number', 'lokalitetsnummer', 'site_code', 'code', 'approval_number',
                         'year', 'year_class', 'week', 'reference', 'phone'})
NAMING_ENDINGS = ('_number', 'nummer', '_code', '_reference')


def names(parts):
    """Whether the leaf at these path parts (the keys from the content's top; a list's index is not a key) names
    something: an identifier, a code or a year, by its key, or anything under the content's identity or facility."""
    keys = [part for part in parts if not part.isdigit()]
    if not keys:
        return False
    return (keys[-1] in NAMING_KEYS or keys[-1].endswith(NAMING_ENDINGS) or 'identity' in keys[:-1]
            or (keys[0] == 'facility' and len(keys) > 1))


def shown(value, zone=None, codes=None, naming=False):
    """A content value as the page says it: a coded value in words, a number in the language's way (its decimals kept),
    yes or no, a date dd.mm.yyyy, an instant on the site's clock (`zone`; none: the company's) as dd.mm.yyyy HH:MM, a
    dash. `naming`: the value names something (`names`): it is printed as it is written, digits and all. The content
    keeps the machine form (ISO, the instant with its offset): the exports read it as it is."""
    if value is None or value == '':
        return '–'
    if isinstance(value, bool):
        return gettext('Yes') if value else gettext('No')
    if codes and isinstance(value, str) and value in codes:
        return str(codes[value])
    if naming and isinstance(value, (int, str)):
        return str(value)
    if isinstance(value, (int, float, Decimal)) or (isinstance(value, str) and re.fullmatch(r'-?\d+(\.\d+)?', value)):
        try:
            number = Decimal(str(value))
        except InvalidOperation:
            return str(value)
        places = max(-number.as_tuple().exponent, 0)
        return formats.number_format(number, places, use_l10n=True, force_grouping=isinstance(value, int) or places == 0)
    if isinstance(value, str) and ISO_DAY.match(value):
        day = read_day(value)
        if day is not None:
            return formats.date_format(day, 'DATE_FORMAT')
    moment = stored_moment(value)
    if moment is not None:
        return formats.date_format(timezone.localtime(moment, zone or company_zone()), 'DATETIME_FORMAT')
    return str(value)


def outline(content, zone=None):
    """[(words, shown value)] of every figure of `content` but what the page's heading says and record references; an
    instant on `zone`'s clock (the report's site)."""
    rows = []

    def walk(node, parts):
        if isinstance(node, dict):
            for key, item in node.items():
                if not parts and key in HEADED:
                    continue
                walk(item, parts + [str(key)])
        elif isinstance(node, list) and node and any(isinstance(item, (dict, list)) for item in node):
            for index, item in enumerate(node):
                walk(item, parts + [str(index)])
        elif not (isinstance(node, str) and RECORD_ID.match(node)):
            codes, naming = codes_for(parts), names(parts)
            value = (', '.join(shown(item, zone, codes, naming) for item in node) if isinstance(node, list)
                     else shown(node, zone, codes, naming))
            rows.append((_words(parts, content), value))
    walk(content, [])
    return rows
