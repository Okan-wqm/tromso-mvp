"""A check of a value against a JSON schema of Mattilsynet's OpenAPI (mattilsynet_schemas.json): the subset of JSON
Schema those schemas use (type, possibly with null; required; properties; items; minItems; enum; pattern; minimum,
maximum and their exclusive forms; $ref and allOf). Written for the tests rather than adding a dependency.

`unknownProperties` is listed as required on some objects of the OpenAPI: a Java artefact (a map the server collects
unknown properties into), not a field to send; the exports leave it out and this check does not ask for it
(docs/regulatory-reports.md, 5.5; whether the server wants `{}` there is unverified)."""
import json
import pathlib
import re

SCHEMAS = json.loads((pathlib.Path(__file__).with_name('mattilsynet_schemas.json')).read_text(encoding='utf-8'))
TYPES = {'object': dict, 'array': list, 'string': str, 'boolean': bool}
ARTEFACTS = {'unknownProperties'}


def _resolve(schema):
    while '$ref' in schema:
        schema = SCHEMAS['schemas'][schema['$ref'].rsplit('/', 1)[-1]]
    return schema


def _type_ok(value, name):
    if name == 'null':
        return value is None
    if name == 'integer':
        return isinstance(value, int) and not isinstance(value, bool)
    if name == 'number':
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return isinstance(value, TYPES[name])


def errors(value, schema, path='$'):
    """[(path, what is wrong)] of `value` against `schema` (a name of mattilsynet_schemas.json, or a schema)."""
    if isinstance(schema, str):
        schema = SCHEMAS['schemas'][schema]
    schema = _resolve(schema)
    found = []
    for part in schema.get('allOf', []):
        found += errors(value, part, path)
    types = schema.get('type')
    if types is not None:
        types = types if isinstance(types, list) else [types]
        if not any(_type_ok(value, name) for name in types):
            return found + [(path, f'is {type(value).__name__}, not {types}')]
    if value is None:
        return found
    if 'enum' in schema and value not in schema['enum']:
        found.append((path, f'{value!r} is not one of {schema["enum"]}'))
    if isinstance(value, str) and 'pattern' in schema and not re.search(schema['pattern'], value):
        found.append((path, f'{value!r} does not match {schema["pattern"]}'))
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        for key, bad in (('minimum', lambda limit: value < limit), ('maximum', lambda limit: value > limit),
                         ('exclusiveMinimum', lambda limit: value <= limit),
                         ('exclusiveMaximum', lambda limit: value >= limit)):
            if key in schema and bad(schema[key]):
                found.append((path, f'{value} breaks {key} {schema[key]}'))
    if isinstance(value, dict):
        for name in schema.get('required', []):
            if name not in value and name not in ARTEFACTS:
                found.append((f'{path}.{name}', 'is required'))
        for name, item in value.items():
            if name in schema.get('properties', {}):
                found += errors(item, schema['properties'][name], f'{path}.{name}')
            elif 'properties' in schema:
                found.append((f'{path}.{name}', 'is not a field of the API'))
    if isinstance(value, list):
        if len(value) < schema.get('minItems', 0):
            found.append((path, f'has fewer than {schema["minItems"]} items'))
        for index, item in enumerate(value):
            found += errors(item, schema.get('items', {}), f'{path}[{index}]')
    return found
