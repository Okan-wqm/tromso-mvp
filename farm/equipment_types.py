"""The equipment type catalogue: every kind of equipment and its technical specifications, in the
schema format of core.schema. It is reference data that migrations write into `equipment_types`
(`sync`); a change here ships with a migration that calls `sync` again, and a test fails while the
database and this file differ.

Ported from the source's seed (apps/farm-service/src/equipment/seeds/equipment-types.seed.ts) with
these differences (docs/aquaculture-platform-bugs.md, EQ-17 to EQ-20):
- no tank, pond or cage types: those are not equipment here, they get their own tab;
- English throughout (the source mixed Turkish labels and descriptions into the English screen), in
  sentence case, and a description only where it says more than the name;
- metric units throughout (the blower and the aerator were in CFM, PSI and HP next to kW and m³/h);
- bounds where the source had none: no negative quantity, percentages from 0 to 100, counts whole;
- the heat exchanger no longer requires a fuel type (a copy of the heater's fields), and "Other
  equipment" no longer has a notes field next to the equipment's own notes;
- no `icon`, `allowedSubEquipmentTypes` or `isSystem`: nothing used them.

The texts are msgids, marked here for the catalogs (gettext_noop) and translated when shown.
Product and standard names (WiFi, Modbus, HDPE) are not translated."""
from django.utils.translation import gettext_noop as _

def _number(name, label, unit='', **extra):
    return {'name': name, 'label': label, 'type': 'number', **({'unit': unit} if unit else {}), 'min': 0, **extra}


def _percent(name, label, **extra):
    return _number(name, label, '%', max=100, **extra)


def _count(name, label, **extra):
    return _number(name, label, integer=True, **extra)


def _select(name, label, options, **extra):
    return {'name': name, 'label': label, 'type': 'select',
            'options': [{'value': value, 'label': text} for value, text in options], **extra}


def _text(name, label, **extra):
    return {'name': name, 'label': label, 'type': 'text', **extra}


def _type(code, name, category, order, fields, description='', groups=()):
    return {'code': code, 'name': name, 'category': category, 'sort_order': order, 'description': description,
            'specification_schema': {**({'groups': list(groups)} if groups else {}), 'fields': fields}}


PHASES = [('single', _('Single-phase')), ('three', _('Three-phase'))]
PUMP_FIELDS = [
    _number('flowRate', _('Flow rate'), 'm³/h', required=True, group='performance'),
    # Translators: the delivery head of a pump, the height it lifts water to.
    _number('head', _('Head'), 'm', group='performance'),
    _number('power', _('Power'), 'kW', group='electrical'),
    _number('voltage', _('Voltage'), 'V', group='electrical'),
    # Translators: the electrical phase of the supply (single-phase or three-phase).
    _select('phase', _('Phase'), PHASES, group='electrical'),
]
PUMP_GROUPS = [{'name': 'performance', 'label': _('Performance')}, {'name': 'electrical', 'label': _('Electrical')}]
AIR_FIELDS = [
    _number('airflow', _('Airflow'), 'm³/h', required=True),
    _number('pressure', _('Pressure'), 'mbar'),
    _number('power', _('Power'), 'kW'),
]
FUELS = [('electric', _('Electric')), ('gas', _('Gas')), ('oil', _('Oil')), ('solar', _('Solar'))]
CONNECTIVITY = [('wifi', 'WiFi'), ('4g5g', '4G/5G'), ('rs485', 'RS485'), ('modbus', 'Modbus'), ('analog', _('Analog'))]
FEEDER_CONTROL = [('timer', _('Timer')), ('remote', _('Remote')), ('automatic', _('Automatic'))]


def _feeder(code, name, order, controlled, description=''):
    fields = [
        _number('capacity', _('Capacity'), 'kg', required=True),
        # Translators: a placeholder showing what to type.
        _text('feedingRate', _('Feeding rate'), placeholder=_('e.g. 1–10 kg/h')),
        *([_select('controlType', _('Control type'), FEEDER_CONTROL)] if controlled else []),
        _number('siloVolume', _('Silo volume'), 'L', required=True),
        {'name': 'autoFilling', 'label': _('Automatic filling'), 'type': 'boolean',
         'helpText': _('The silo is filled automatically.')},
    ]
    return _type(code, name, 'feeding', order, fields, description)


def _sensor(code, name, order, example, description='', first=()):
    fields = [
        *first,
        _text('measurementRange', _('Measurement range'), placeholder=example, required=not first),
        _text('accuracy', _('Accuracy')),
        _select('connectivity', _('Connectivity'), CONNECTIVITY),
        {'name': 'calibrationDate', 'label': _('Last calibration'), 'type': 'date'},
    ]
    return _type(code, name, 'monitoring', order, fields, description)


TYPES = [
    _type('pump-centrifugal', _('Centrifugal pump'), 'pump', 14, PUMP_FIELDS, groups=PUMP_GROUPS),
    _type('pump-submersible', _('Submersible pump'), 'pump', 15, PUMP_FIELDS, groups=PUMP_GROUPS),

    _type('blower', _('Blower'), 'aeration', 20, AIR_FIELDS),
    _type('aerator', _('Aerator'), 'aeration', 21, AIR_FIELDS),

    _type('heater', _('Heater'), 'heating_cooling', 30, [
        _number('heatingCapacity', _('Heating capacity'), 'kW', required=True),
        _number('powerConsumption', _('Power consumption'), 'kW'),
        _percent('efficiency', _('Efficiency')),
        _select('fuelType', _('Fuel type'), FUELS, required=True),
        {'name': 'maxTemperature', 'label': _('Maximum temperature'), 'type': 'number', 'unit': '°C'},
    ]),
    _type('chiller', _('Chiller'), 'heating_cooling', 31, [
        _number('coolingCapacity', _('Cooling capacity'), 'kW', required=True),
        _number('powerConsumption', _('Power consumption'), 'kW'),
        # Translators: the coefficient of performance of a chiller.
        _number('cop', _('COP (efficiency)')),
        _text('refrigerantType', _('Refrigerant'), placeholder=_('e.g. R410A')),
        _number('maxFlowRate', _('Maximum flow rate'), 'm³/h'),
    ]),
    _type('heat-exchanger', _('Heat exchanger'), 'heating_cooling', 32, [
        _number('heatingCapacity', _('Heating capacity'), 'kW', required=True),
        _number('powerConsumption', _('Power consumption'), 'kW'),
        _percent('efficiency', _('Efficiency')),
        {'name': 'maxTemperature', 'label': _('Maximum temperature'), 'type': 'number', 'unit': '°C'},
    ]),

    _type('filter-mechanical', _('Mechanical filter'), 'filtration', 40, [
        _number('flowRate', _('Flow rate'), 'm³/h', required=True),
        _number('filtrationSize', _('Filtration size'), 'µm'),
        _text('mediaType', _('Filter medium'), placeholder=_('e.g. sand, cartridge')),
    ]),
    _type('filter-biological', _('Biological filter'), 'filtration', 41, [
        _number('flowRate', _('Flow rate'), 'm³/h', required=True),
        _number('mediaVolume', _('Media volume'), 'L'),
        _select('mediaType', _('Bed type'), [('moving_bed', _('Moving bed (MBBR)')), ('fixed_bed', _('Fixed bed')),
                                               ('fluidized_bed', _('Fluidised bed'))]),
        _number('surfaceArea', _('Specific surface area'), 'm²/m³'),
    ]),
    _type('filter-uv', _('UV filter'), 'filtration', 42, [
        _number('flowRate', _('Flow rate'), 'm³/h', required=True),
        _number('uvDose', _('UV dose'), 'mJ/cm²'),
        _number('power', _('Power'), 'W'),
        _count('lampCount', _('Number of lamps'), min=1),
    ]),
    _type('filter-drum', _('Drum filter'), 'filtration', 43, [
        _number('flowRate', _('Flow rate'), 'm³/h', required=True),
        _number('screenSize', _('Screen size'), 'µm'),
        _number('drumDiameter', _('Drum diameter'), 'mm'),
        _number('backwashInterval', _('Backwash interval'), 'min'),
    ]),
    _type('filter-bead', _('Bead filter'), 'filtration', 44, [
        _number('flowRate', _('Flow rate'), 'm³/h', required=True),
        _number('beadVolume', _('Bead volume'), 'L'),
        _select('beadType', _('Bead material'), [('polyethylene', _('Polyethylene')),
                                                  ('polypropylene', _('Polypropylene'))]),
        _text('backwashFrequency', _('Backwash frequency'), placeholder=_('e.g. daily')),
    ]),

    _feeder('feeder-automatic', _('Automatic feeder'), 50, controlled=True),
    _feeder('feeder-demand', _('Demand feeder'), 51, controlled=True,
            description=_('Feeds when the fish trigger it.')),
    _feeder('feeder-semi-automatic', _('Semi-automatic feeder'), 52, controlled=False),

    _type('tank-inlet', _('Tank inlet'), 'plumbing', 53, [
        _number('pipeSize', _('Pipe size'), 'mm', required=True, defaultValue=110),
        _count('holeCount', _('Distribution holes'), defaultValue=6),
        _select('material', _('Material'), [('pvc', 'PVC'), ('hdpe', 'HDPE'), ('stainless', _('Stainless steel'))],
                defaultValue='pvc'),
    ], description=_('The pipe that lets water into a tank through distribution holes.')),

    _sensor('sensor-temperature', _('Temperature sensor'), 60, _('e.g. 0–50 °C')),
    _sensor('sensor-ph', _('pH sensor'), 61, _('e.g. 0–14 pH')),
    _sensor('sensor-do', _('Dissolved oxygen sensor'), 62, _('e.g. 0–20 mg/L')),
    _sensor('sensor-salinity', _('Salinity sensor'), 63, _('e.g. 0–50 ppt')),
    _sensor('sensor-ammonia', _('Ammonia sensor'), 64, _('e.g. 0–10 mg/L')),
    _sensor('sensor-flow', _('Flow sensor'), 65, _('e.g. 0–100 m³/h')),
    _sensor('sensor-level', _('Level sensor'), 66, _('e.g. 0–10 m')),
    _sensor('sensor-pressure', _('Pressure sensor'), 67, _('e.g. 0–10 bar')),
    _sensor('sensor-multiparameter', _('Multiparameter probe'), 68, _('e.g. by parameter'),
            description=_('One probe that measures several water parameters.'),
            first=[{'name': 'parameters', 'label': _('Measured parameters'), 'type': 'multiselect', 'required': True,
                    'options': [{'value': value, 'label': text} for value, text in [
                        ('temperature', _('Temperature')), ('ph', 'pH'), ('do', _('Dissolved oxygen')),
                        ('salinity', _('Salinity')), ('conductivity', _('Conductivity')),
                        ('turbidity', _('Turbidity'))]]}]),

    _type('generator', _('Generator'), 'electrical', 70, [
        _number('powerOutput', _('Power output'), 'kW', required=True),
        _select('fuelType', _('Fuel type'), [('diesel', _('Diesel')), ('gasoline', _('Petrol')),
                                              ('natural_gas', _('Natural gas')), ('propane', _('Propane'))],
                required=True),
        _number('fuelConsumption', _('Fuel consumption'), 'L/h'),
    ], description=_('Backup power supply.')),

    _type('uv-sterilizer', _('UV steriliser'), 'water_treatment', 80, [
        _number('flowRate', _('Flow rate'), 'm³/h', required=True),
        _number('uvDose', _('UV dose'), 'mJ/cm²', required=True),
        _number('power', _('Power'), 'W', required=True),
        _count('lampCount', _('Number of lamps'), min=1),
        _select('lampType', _('Lamp type'), [('low_pressure', _('Low pressure')), ('medium_pressure', _('Medium pressure')),
                                              ('amalgam', _('Amalgam'))]),
        _number('lampLifeHours', _('Lamp life'), 'h'),
        _percent('transmittance', _('Minimum transmittance')),
    ]),
    _type('ozone-generator', _('Ozone generator'), 'water_treatment', 81, [
        _number('ozoneProduction', _('Ozone production'), 'g/h', required=True),
        _number('power', _('Power'), 'kW', required=True),
        _select('generationType', _('Generation method'), [('corona', _('Corona discharge')), ('uv', 'UV')],
                required=True),
        _select('feedGas', _('Feed gas'), [('air', _('Air')), ('oxygen', _('Oxygen'))]),
        _percent('concentration', _('Ozone concentration')),
        _select('coolingType', _('Cooling'), [('air', _('Air')), ('water', _('Water'))]),
    ]),

    _type('other', _('Other equipment'), 'other', 100, [
        _text('customField1', _('Custom field 1')),
        _text('customField2', _('Custom field 2')),
        _text('customField3', _('Custom field 3')),
    ], description=_('Equipment that fits none of the other types.')),
]


def sync(apps, schema_editor):
    """Writes the catalogue into `equipment_types` (a migration's RunPython), by code: new types are
    added, listed ones brought in line and offered, a type no longer listed stays (its equipment keeps
    it) but is no longer offered."""
    EquipmentType = apps.get_model('farm', 'EquipmentType')
    for entry in TYPES:
        EquipmentType.objects.update_or_create(code=entry['code'], defaults={
            **{key: value for key, value in entry.items() if key != 'code'}, 'is_active': True})
    EquipmentType.objects.exclude(code__in=[entry['code'] for entry in TYPES]).update(is_active=False)
