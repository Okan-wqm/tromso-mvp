"""The one label registry of a report's content (reports/compute): every key the computation writes, named as the report
pages name it, translated (reports/tests/test_labels.py reads the computation's code, so a new key cannot slip by). Both
the report page (`outline`: the figures of a kind without a table of its own, sea lice and cleaner fish) and a filed
report's differences (`describe`: "Unit K-02 · Fish at the month’s end") read it, so no page shows a content or API key;
a number is said as the person's language writes it."""
import re
from decimal import Decimal, InvalidOperation

from django.utils import formats
from django.utils.translation import gettext, gettext_lazy as _, pgettext_lazy

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
UNNAMED = _('(unnamed figure)')
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


def shown(value):
    """A content value as the page says it: a number in the language's way (its decimals kept), yes or no, a dash."""
    if value is None or value == '':
        return '–'
    if isinstance(value, bool):
        return gettext('Yes') if value else gettext('No')
    if isinstance(value, (int, float, Decimal)) or (isinstance(value, str) and re.fullmatch(r'-?\d+(\.\d+)?', value)):
        try:
            number = Decimal(str(value))
        except InvalidOperation:
            return str(value)
        places = max(-number.as_tuple().exponent, 0)
        return formats.number_format(number, places, use_l10n=True, force_grouping=isinstance(value, int) or places == 0)
    return str(value)


def outline(content):
    """[(words, shown value)] of every figure of `content` but what the page's heading says and record references."""
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
            value = ', '.join(shown(item) for item in node) if isinstance(node, list) else shown(node)
            rows.append((_words(parts, content), value))
    walk(content, [])
    return rows
