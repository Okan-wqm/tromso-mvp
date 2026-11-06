"""A place in a report's content (reports/compute: a path such as /units/<id>/avg_weight_g) said as the report's page names it:
"Unit K-02 · Average weight (g)". What changed in a filed report's records is told so (services.differences), never as the
content's keys: a record is named by its number or name, a figure by its label on the page."""
from django.utils.translation import gettext_lazy as _, pgettext_lazy

# A key of the content: the words the report's page (templates/reports/_figures.html) gives it.
FIELDS = {
    'fish_at_end': _('Fish at the month’s end'),
    'avg_weight_g': _('Average weight (g)'),
    'culled': _('Culled'),
    'died': _('Died'),
    'moved_out_of_site': _('Moved out of the site'),
    'number': _('Unit number'),
    'species': pgettext_lazy('singular', 'Species'),
    'organisation_number': _('Organisation number'),
    'lokalitetsnummer': _('Lokalitetsnummer'),
    'year_class': _('Year class'),
    'fish': _('Fish'),
    'kg': _('kg'),
    'biomass_kg': _('Biomass (kg)'),
    'stock': _('Stock at the month’s end'),
    'stocked': _('Stocked'),
    'harvested': _('Harvested'),
    'moved_out': _('Moved to another site'),
    'losses': _('Lost'),
    'feed': _('Feed'),
    'temperature_c': _('Sea temperature (°C)'),
    'counts': _('Lice counts'),
    'treatments': _('Treatments'),
    'occurred_on': _('Happened on'),
    'site': _('Site'),
}
# A key whose children are records named by their own number or name.
RECORDS = {'units': _('Unit %(name)s'), 'localities': _('Site %(name)s')}
# A key that only groups (the identity is said apart, as "Identity").
SILENT = {'identity'}


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
    return key


def describe(path, *contents):
    """The words for `path`, read in the first of `contents` that has it (what was filed, else what the records give now)."""
    parts = [part for part in path.strip('/').split('/') if part]
    content = next((item for item in contents if _reaches(item, parts)), contents[0] if contents else {})
    words, node, parent = [], content, None
    for part in parts:
        child = _child(node, part)
        if parent in RECORDS:
            words.append(str(RECORDS[parent] % {'name': _name(child, part)}))
        elif isinstance(node, list):
            words.append(f'#{int(part) + 1}' if part.isdigit() else part)
        elif part not in SILENT and part not in RECORDS:
            words.append(str(FIELDS.get(part, part.replace('_', ' ').capitalize())))
        node, parent = child, part
    return ' · '.join(words)


def _reaches(content, parts):
    node = content
    for part in parts[:-1]:
        node = _child(node, part)
        if node is None:
            return False
    return True
