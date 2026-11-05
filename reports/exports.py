"""A report as a file a person files from: CSV (section, the authority's field name, value) for every kind, and JSON in
the shape of Mattilsynet's reporting API for the kinds it takes, its fields as the API's OpenAPI names them (read
2026-11-03; docs/regulatory-reports.md, section 1). Both are built from the content: the frozen one once the report
is filed, else the content the records give now (the page says which). The field names stay Norwegian, as the
authority writes them."""
import csv
import io

from django.utils.translation import gettext

from core.dbgrid import formula_safe

from .kinds import ReportKind

# The reports Mattilsynet's reporting API takes: the kinds `api_json` builds.
API_KINDS = (ReportKind.SEA_LICE, ReportKind.SMOLT, ReportKind.CLEANER_FISH, ReportKind.SLAUGHTER_PLANNED)
CULL_FIELDS = {'sick': 'antallAvlivetSykdom', 'injured': 'antallAvlivetSkader', 'emaciated': 'antallAvlivetAvmagret',
               'salmon_handling': 'antallAvlivetForeståendeHåndteringAvLaksen',
               'poor_environment': 'antallAvlivetForeståendeUgunstigLevemiljø', 'not_used': 'antallAvlivetSkalIkkeBrukes'}
ORIGINS = {'farmed': 'OPPDRETTET', 'wild_caught': 'VILLFANGET'}
BOTH_ORIGINS = 'VILLFANGET_OG_OPPDRETTET'      # "if the fish comes from both farming and fishing": one row per species
SPECIES_FIGURES = ('opening', 'stocked', 'moved_in', 'died', 'moved_out', 'unaccounted')
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


def _per_species(rows):
    """The cleaner-fish rows of a unit as the API takes them: one per species (`ArtDto` is per species), the figures of its
    origins added together and the origin the mixed value when both farmed and wild-caught fish are in it."""
    species = {}
    for row in rows:
        merged = species.get(row['species'])
        if merged is None:
            species[row['species']] = {**row, 'culled': dict(row['culled']), 'origins': {row['origin']}}
            continue
        for name in SPECIES_FIGURES:
            merged[name] += row[name]
        for cause, fish in row['culled'].items():
            merged['culled'][cause] += fish
        merged['origins'].add(row['origin'])
    found = []
    for row in species.values():
        origins = {ORIGINS.get(origin) for origin in row['origins']}
        found.append({**row, 'origin': BOTH_ORIGINS if len(origins) > 1 else origins.pop()})
    return found


# The reporting API's endpoints (docs/regulatory-reports.md, 7.2): a report is a POST; a correction of the kinds that have it is a
# PUT to the id the first POST returned. The sea-lice endpoint has POST only.
ENDPOINTS = {ReportKind.SEA_LICE: '/api/lakselus/v1/lakselus', ReportKind.SMOLT: '/api/settefisk/v1/settefisk',
             ReportKind.CLEANER_FISH: '/api/rensefisk/v1/rensefisk',
             ReportKind.SLAUGHTER_PLANNED: '/api/slakt/v1/planlagt'}
PUT_KINDS = (ReportKind.SMOLT, ReportKind.CLEANER_FISH, ReportKind.SLAUGHTER_PLANNED)


def api_call(report):
    """How the reporting API takes this report: {'method', 'path', 'client_reference', 'corrects_client_reference',
    'note'}; None for a kind it has no endpoint for. A correction of a smolt, cleaner-fish or planned-slaughter report is a PUT to
    the id the authority returned for the original (`Report.authority_id`; the note says when it was not recorded), under its own
    client reference; the original's is given so the sender can find what it replaces. A correction of a sea-lice report is a
    POST again (the endpoint has no PUT: whether a second POST for the week replaces or duplicates is unverified, R02)."""
    path = ENDPOINTS.get(report.kind)
    if path is None:
        return None
    call = {'method': 'POST', 'path': path, 'client_reference': str(report.pk), 'corrects_client_reference': None,
            'note': ''}
    original = report.corrects
    if original is None:
        return call
    call['corrects_client_reference'] = str(original.pk)
    if report.kind in PUT_KINDS:
        if original.authority_id:
            call.update(method='PUT', path=f'{path}/{original.authority_id}')
        else:
            call.update(method='PUT', path=f'{path}/{{id}}', note=gettext(
                'The id the authority returned for the first filing was not recorded: it is needed to correct it.'))
    else:
        call['note'] = gettext('The sea-lice endpoint has no PUT: a correction is sent again as a POST (whether it '
                               'replaces the week or duplicates it is unverified).')
    return call


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
                        'artskode': found['species'], 'opprinnelse': found['origin'],
                        'beholdningVedForrigeMånedsslutt': found['opening'],
                        'utsett': {'antallNy': found['stocked'], 'antallFlyttetInn': found['moved_in']},
                        'uttak': {**{CULL_FIELDS[cause]: fish for cause, fish in found['culled'].items()},
                                  'antallSelvdød': found['died'], 'antallFlyttetUt': found['moved_out'],
                                  'antallKanIkkeGjøresRedeFor': found['unaccounted']},
                    } for found in _per_species(unit['species'])],
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
        return {**base, 'uke': week, 'år': year,
                'organisasjonsnummer': content['facility']['organisation_number'],
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
