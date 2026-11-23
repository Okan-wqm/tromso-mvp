"""What a sensor channel measures: the ONE catalogue of quantities. The water quantities are the water parameters
themselves (farm/water/parameters.py: the same code, unit, decimals and plausible range), so a sensor's oxygen is the
oxygen a manual sample records and the same limits judge it; the others (conductivity, ORP, flow, level, pressure, power,
current) are process quantities, judged by nobody yet and drawn on charts.

Each quantity carries the defaults a new channel starts from: the deadband (an absolute change in the engineering unit
below which a value is not stored again), the heartbeat (a value is stored at least this often even when it does not
move), the range (a value outside it is stored flagged OUT_OF_RANGE, sensors/quality.py) and the reduction. The defaults
are COPIED into the channel row when it is created: the ingest service reads the row, never this file, so the row is
the authority and a later change here does not move an existing channel.

Oxygen and temperature keep every message (`reduction='all'`, owner default): they are the survival variables of a
life-support loop. A channel's deadband may not be finer than the quantity's `step` (a water parameter's decimals): a
smaller change than the recorded precision is noise.

The CHECK of `sensors_channel.quantity` lists these codes; a new quantity is a new migration."""
from dataclasses import dataclass
from decimal import Decimal

from django.utils.translation import gettext_lazy as _

from farm.water import parameters

ALL, DEADBAND = 'all', 'deadband'
# A sensor's pH is stored as the device sends it, on its channel's pH scale (sensors.Channel.ph_scale; owner decision 1
# of 2026-11-17, the water-chemistry audit of 2026-11-19, F1), and put on the NBS scale where the water is read
# (farm/water/read.py Context.sensor_ph), with the temperature and the salinity of the same moment.
PH_SCALE_NOTE = _('A pH channel says the scale its probe reports on (its pH scale). A probe calibrated with TRIS (most '
                  'sea-water ISFET and optical sensors) reports on the total scale, 0.09 to 0.15 lower than NBS in sea '
                  'water: taken as NBS its NH₃ would read 19 to 28 % low.')
PH_SCALE_HELP = _('The scale the probe reports its pH on: NBS (calibrated with NBS/NIST buffers), or the total (TRIS), '
                  'seawater or free scale. Other than NBS, each value is put on the NBS scale where the water is worked '
                  'out, with the temperature (a sensor’s, else a sample’s fresh then) and the salinity of the same '
                  'moment, for sea water of 5 ‰ or more; otherwise the pH and its NH₃ cannot be evaluated, and the page says why. Changing it: '
                  'what the probe measured before is used nowhere after (its scale is not known).')


@dataclass(frozen=True)
class Quantity:
    code: str
    label: str
    unit: str                # the engineering unit stored values are in
    step: Decimal            # the finest deadband that makes sense
    deadband: Decimal
    heartbeat_s: int
    low: Decimal
    high: Decimal
    reduction: str = DEADBAND
    water: bool = False      # a water parameter: shown through the water read (farm/water/read.py) and judged by its limits

    @property
    def decimals(self):
        """The decimals a value of it is said with: those of its step (a water parameter's own, farm/water/parameters.py)."""
        return max(-self.step.normalize().as_tuple().exponent, 0)

    @property
    def parameter(self):
        """The water parameter, for a water quantity; None otherwise."""
        return parameters.get(self.code) if self.water else None


def _d(value):
    return Decimal(str(value))


# The engineering unit of each water parameter (the parameter's label names it with its basis).
WATER_UNITS = {
    'temperature_c': '°C', 'oxygen_mg_l': 'mg/L', 'oxygen_saturation_pct': '%', 'ph': 'pH', 'alkalinity_mg_l': 'mg/L',
    'co2_mg_l': 'mg/L', 'tan_mg_l': 'mg/L', 'nitrite_n_mg_l': 'mg/L', 'nitrate_n_mg_l': 'mg/L', 'tgp_pct': '%',
    'salinity_ppt': '‰', 'turbidity_ntu': 'NTU', 'hardness_mg_l': 'mg/L', 'conductivity_25_us_cm': 'µS/cm',
    'phosphate_p_mg_l': 'mg/L',
}
# (deadband, heartbeat seconds, reduction) of each water parameter.
WATER_DEFAULTS = {
    'temperature_c': ('0.1', 60, ALL),
    'oxygen_mg_l': ('0.1', 300, ALL),
    'oxygen_saturation_pct': ('1', 300, ALL),
    'ph': ('0.02', 300, DEADBAND),
    'alkalinity_mg_l': ('1', 3600, DEADBAND),
    'co2_mg_l': ('0.5', 300, DEADBAND),
    'tan_mg_l': ('0.01', 900, DEADBAND),
    'nitrite_n_mg_l': ('0.01', 900, DEADBAND),
    'nitrate_n_mg_l': ('0.5', 900, DEADBAND),
    'tgp_pct': ('0.5', 300, DEADBAND),
    'salinity_ppt': ('0.2', 600, DEADBAND),
    'turbidity_ntu': ('1', 600, DEADBAND),
    'hardness_mg_l': ('1', 3600, DEADBAND),
    'conductivity_25_us_cm': ('5', 300, DEADBAND),
    'phosphate_p_mg_l': ('0.05', 3600, DEADBAND),
}

WATER = [
    Quantity(parameter.code, parameter.label, WATER_UNITS[parameter.code], parameter.step,
             _d(WATER_DEFAULTS[parameter.code][0]), WATER_DEFAULTS[parameter.code][1], parameter.low, parameter.high,
             WATER_DEFAULTS[parameter.code][2], water=True)
    for parameter in parameters.MEASURED
]
PROCESS = [
    # At the water's own temperature: the chemistry never reads it (only the compensated water parameter,
    # conductivity_25_us_cm, cross review F8).
    Quantity('conductivity_us_cm', _('Conductivity at the water’s temperature (µS/cm, not compensated)'), 'µS/cm', _d(1),
             _d(5), 300, _d(0), _d(100000)),
    Quantity('orp_mv', _('Redox potential, ORP (mV)'), 'mV', _d(1), _d(5), 300, _d(-1000), _d(1000)),
    Quantity('flow_m3_h', _('Flow (m³/h)'), 'm³/h', _d('0.01'), _d(10), 300, _d(0), _d(1000)),
    Quantity('level_mm', _('Level (mm)'), 'mm', _d(1), _d(5), 300, _d(0), _d(10000)),
    Quantity('pressure_bar', _('Pressure (bar)'), 'bar', _d('0.001'), _d('0.01'), 300, _d(-1), _d(100)),
    Quantity('power_kw', _('Power (kW)'), 'kW', _d('0.001'), _d('0.05'), 300, _d(0), _d(10000)),
    Quantity('current_a', _('Electric current (A)'), 'A', _d('0.01'), _d('0.1'), 300, _d(0), _d(10000)),
]
ALL_QUANTITIES = [*WATER, *PROCESS]
BY_CODE = {quantity.code: quantity for quantity in ALL_QUANTITIES}
CODES = [quantity.code for quantity in ALL_QUANTITIES]
WATER_CODES = [quantity.code for quantity in WATER]
CHOICES = [(quantity.code, quantity.label) for quantity in ALL_QUANTITIES]


def get(code):
    return BY_CODE[code]


def defaults(code):
    """The values a new channel of this quantity starts from: copied into its row."""
    quantity = BY_CODE[code]
    return {'unit': quantity.unit, 'deadband': float(quantity.deadband), 'heartbeat_s': quantity.heartbeat_s,
            'range_min': float(quantity.low), 'range_max': float(quantity.high), 'reduction': quantity.reduction}
