"""A report as a file a person files from: CSV (section, the authority's field name, value) for every kind, and JSON in
the shape of Mattilsynet's reporting API for the kinds it takes, its fields as the API's OpenAPI names them (read
2026-11-03; docs/regulatory-reports.md, section 1). Both are built from the content: the frozen one once the report
is filed, else the content the records give now (the page says which). The field names stay Norwegian, as the
authority writes them."""
import csv
import io

from core.dbgrid import formula_safe

from .kinds import ReportKind

CULL_FIELDS = {'sick': 'antallAvlivetSykdom', 'injured': 'antallAvlivetSkader', 'emaciated': 'antallAvlivetAvmagret',
               'salmon_handling': 'antallAvlivetForeståendeHåndteringAvLaksen',
               'poor_environment': 'antallAvlivetForeståendeUgunstigLevemiljø', 'not_used': 'antallAvlivetSkalIkkeBrukes'}
ORIGINS = {'farmed': 'OPPDRETTET', 'wild_caught': 'VILLFANGET'}
WEEKDAY_FIELDS = {'monday': 'mandagKg', 'tuesday': 'tirsdagKg', 'wednesday': 'onsdagKg', 'thursday': 'torsdagKg',
                  'friday': 'fredagKg', 'saturday': 'lørdagKg', 'sunday': 'søndagKg'}


def contact(report):
    return {'navn': report.contact_name, 'epost': report.contact_email, 'telefonnummer': report.contact_phone}


def _number(text):
    """A decimal kept as text in the content, as a JSON number."""
    if text is None:
        return None
    value = float(text)
    return int(value) if value == int(value) else value


def _non_medicinal(item):
    return {'type': item['type'], 'beskrivelse': item['description'], 'gjennomførtFørTelling': item['before_count'],
            'heleLokaliteten': item['whole_site'], 'antallMerder': item['cages']}


def _medicinal(item):
    substance = item['substance']
    return {'type': item['type'], 'beskrivelse': item['description'], 'gjennomførtFørTelling': item['before_count'],
            'heleLokaliteten': item['whole_site'], 'antallMerder': item['cages'],
            'virkestoff': {
                'type': substance['type'], 'annetVirkestoff': substance['other'],
                'styrke': {'verdi': _number(substance['strength']['value']), 'enhet': substance['strength']['unit']},
                'mengde': {'verdi': _number(substance['amount']['value']), 'enhet': substance['amount']['unit']}}}


def _lice(report, content, base):
    """The weekly lice report as LakselusrapporteringDto: the treatments given together are a combination each, the
    rest are listed on their own."""
    year, week = report.period.iso
    identity = content['identity']
    alone = [item for item in content['treatments'] if item['combination'] is None]
    together = {}
    for item in content['treatments']:
        if item['combination'] is not None:
            together.setdefault(item['combination'], []).append(item)
    counts = content['counts']
    body = {**base, 'organisasjonsnummer': identity['organisation_number'], 'lokalitetsnummer': identity['lokalitetsnummer'],
            'rapporteringsår': year, 'rapporteringsuke': week, 'sjøtemperatur': _number(content['temperature_c']),
            'lusetelling': None if counts is None else {
                'voksneHunnlus': _number(counts['adult_females']), 'bevegeligeLus': _number(counts['mobile']),
                'fastsittendeLus': _number(counts['attached'])},
            'ikkeMedikamentelleBehandlinger': [_non_medicinal(item) for item in alone if not item['medicinal']],
            'medikamentelleBehandlinger': [_medicinal(item) for item in alone if item['medicinal']],
            'kombinasjonsbehandlinger': [{
                'ikkeMedikamentelleBehandlinger': [_non_medicinal(item) for item in items if not item['medicinal']],
                'medikamentelleBehandlinger': [_medicinal(item) for item in items if item['medicinal']],
            } for _number_of, items in sorted(together.items())],
            'resistensMistanker': [{
                'resistens': row['substance'], 'annenResistens': row['other_substance'], 'årsak': row['cause'],
                'annenÅrsak': row['other_cause']} for row in content['resistance_suspicions']],
            'følsomhetsundersøkelser': [{
                'utførtDato': f'{row["tested_on"]}T00:00:00Z', 'laboratorium': row['laboratory'],
                'resistens': row['substance'], 'annenResistens': row['other_substance'],
                'testresultat': row['result']} for row in content['sensitivity_tests']]}
    return body


def api_json(report, content):
    """The report as Mattilsynet's reporting API takes it, or None for a kind the API has no endpoint for."""
    identity = content.get('identity', {})
    base = {'klientReferanse': str(report.pk), 'kontaktperson': contact(report)}
    if report.kind == ReportKind.SEA_LICE:
        return _lice(report, content, base)
    if report.kind == ReportKind.CLEANER_FISH:
        year, month = report.period.iso
        return {**base, 'organisasjonsnummer': identity['organisation_number'], 'rapporteringsmåned': month,
                'rapporteringsår': year, 'lokalitetsnummer': identity['lokalitetsnummer'],
                'tørrforKg': content['feed']['dry_kg'], 'våtforKg': content['feed']['wet_kg'],
                'produksjonsenheter': [{
                    'merdId': unit['number'],
                    'arter': [{
                        'artskode': found['species'], 'opprinnelse': ORIGINS.get(found['origin']),
                        'beholdningVedForrigeMånedsslutt': found['opening'],
                        'utsett': {'antallNy': found['stocked'], 'antallFlyttetInn': found['moved_in']},
                        'uttak': {**{CULL_FIELDS[cause]: fish for cause, fish in found['culled'].items()},
                                  'antallSelvdød': found['died'], 'antallFlyttetUt': found['moved_out'],
                                  'antallKanIkkeGjøresRedeFor': found['unaccounted']},
                    } for found in unit['species']],
                } for unit in sorted(content['units'].values(), key=lambda unit: unit['number'])]}
    if report.kind == ReportKind.SMOLT:
        year, month = report.period.iso
        return {**base, 'organisasjonsnummer': identity['organisation_number'], 'rapporteringsmåned': month,
                'rapporteringsår': year, 'lokalitetsnummer': identity['lokalitetsnummer'],
                'produksjonsenheter': [{
                    'karId': unit['number'], 'artskode': unit['species'],
                    'snittvektGram': _number(unit['avg_weight_g']),
                    'beholdningVedMånedsslutt': unit['fish_at_end'], 'antallAvlivet': unit['culled'],
                    'antallSelvdød': unit['died'], 'antallFlyttetEksternt': unit['moved_out_of_site'],
                } for unit in sorted(content['units'].values(), key=lambda unit: unit['number'])]}
    if report.kind == ReportKind.SLAUGHTER_PLANNED:
        year, week = report.period.iso
        localities = sorted(content['localities'].values(), key=lambda locality: locality['site'])
        organisations = {locality['organisation_number'] for locality in localities}
        return {**base, 'uke': week, 'år': year,
                'organisasjonsnummer': organisations.pop() if len(organisations) == 1 else None,
                'godkjenningsnummer': content['facility']['approval_number'],
                'planlagteLokaliteter': [{
                    'organisasjonsnummer': locality['organisation_number'],
                    'lokalitetsnummer': locality['lokalitetsnummer'],
                    'ukeplanPerArt': [{'artskode': code, **{WEEKDAY_FIELDS[day]: kilos for day, kilos in days.items()}}
                                      for code, days in sorted(locality['species'].items())],
                } for locality in localities]}
    return None


def csv_text(report, content):
    """The report as CSV: one row per field, `section,field,value`; free text guarded against spreadsheet formulas,
    numbers left as numbers."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator='\n')
    writer.writerow(['section', 'field', 'value'])
    for section, field, value in rows(report, content):
        writer.writerow([section, field, formula_safe(value) if isinstance(value, str) else value])
    return out.getvalue()


def rows(report, content):
    """(section, field, value) of every leaf: of the API's shape, with its Norwegian field names, for a kind the API
    takes; else of the content, the contact person first."""
    shaped = api_json(report, content)
    source = shaped if shaped is not None else {'kontaktperson': contact(report), **content}
    found = []
    for key, value in source.items():
        found += _leaves(key, value)
    return found


def _leaves(section, value, field=''):
    if isinstance(value, dict):
        found = []
        for key, item in value.items():
            found += _leaves(section, item, f'{field}.{key}' if field else key)
        return found
    if isinstance(value, list):
        found = []
        for index, item in enumerate(value):
            found += _leaves(section, item, f'{field}[{index}]')
        return found
    return [(section, field, '' if value is None else value)]
