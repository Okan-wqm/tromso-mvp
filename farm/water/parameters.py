"""The water parameters a sample records: a fixed list in code, each with one unit and one basis, so a
value can never be relabelled into another unit (the source's free-text unit, WQ-23) and nitrogen is
always "as N" (WQ-03). The column is named with its unit, as `avg_weight_g` is.

Each parameter declares, once, what the model column, its database check, the form field, the help and
the tables read from it:
- `low`, `high`: the plausible range. These catch a typing slip (pH 25, DO −3, 300 °C: WQ-07); they are
  not limits, which are the owner's per species (WaterLimit). They are a database check per column.
- `decimals`: the precision the column keeps; the column's digits follow from the range.
How long a value says something about the water now is not the code's: it is the user's reference data
(farm/water/freshness.py, farm.WaterFreshness; cross review F10).
The ranges are argued in the bug document (Water chemistry, the plausibility table)."""
from dataclasses import dataclass
from decimal import Decimal

from django.db import models
from django.utils.translation import gettext_lazy as _

# The fieldsets of the record form, in order.
GROUPS = [
    ('oxygen', _('Temperature and oxygen')),
    ('acid', _('Acid–base and CO₂')),
    ('nitrogen', _('Nitrogen')),
    ('other', _('Gas and other')),
]


@dataclass(frozen=True)
class Parameter:
    code: str            # the column and the limit's parameter: temperature_c
    label: str           # the field's label, with its unit and basis: Temperature (°C)
    short: str           # a table's column heading: Temp. (°C)
    decimals: int
    low: Decimal
    high: Decimal
    group: str = ''
    help: str = ''
    measured: bool = True    # False: worked out from other values of the sample (never stored)

    @property
    def max_digits(self):
        """The column's digits: the range's integer digits and the decimals."""
        return len(str(int(max(abs(self.low), abs(self.high))))) + self.decimals

    @property
    def step(self):
        return Decimal(1).scaleb(-self.decimals)

    def field(self):
        """The model column: a decimal with the parameter's precision, empty when not measured."""
        return models.DecimalField(self.label, max_digits=self.max_digits, decimal_places=self.decimals,
                                   null=True, blank=True)

    def plausible(self, value):
        return self.low <= value <= self.high

    def precise(self, value):
        """Whether a value has at most the parameter's decimals."""
        return value == value.quantize(self.step)


def _parameter(code, label, short, decimals, low, high, group='', help='', measured=True):
    return Parameter(code, label, short, decimals, Decimal(str(low)), Decimal(str(high)), group, help, measured)


MEASURED = [
    _parameter('temperature_c', _('Temperature (°C)'), _('Temp. (°C)'), 1, -3, 40, 'oxygen'),
    _parameter('oxygen_mg_l', _('Dissolved oxygen (mg/L O₂)'), _('O₂ (mg/L)'), 2, 0, 50, 'oxygen',
               _('As the meter or kit reads it. With the temperature, the saturation is worked out when it is not '
                 'entered.')),
    _parameter('oxygen_saturation_pct', _('Oxygen saturation (% of air saturation)'), _('O₂ (%)'), 1, 0, 400,
               'oxygen', _('As an oxygen meter shows it; above 100 % with added oxygen. With the temperature, the mg/L '
                           'is worked out when it is not entered.')),
    _parameter('ph', _('pH (NBS scale)'), _('pH'), 2, 2, 12, 'acid',
               _('As a pH meter or kit reads it.')),
    _parameter('alkalinity_mg_l', _('Alkalinity (mg/L as CaCO₃)'), _('Alkalinity (mg/L)'), 0, 0, 1000, 'acid',
               _('Total alkalinity. A kit in dKH: multiply by 17.85.')),
    _parameter('hardness_mg_l', _('Total hardness (mg/L as CaCO₃)'), _('Hardness (mg/L)'), 0, 0, 10000, 'acid',
               _('Calcium and magnesium together, as CaCO₃. A kit in dGH: multiply by 17.85. With the alkalinity it '
                 'gives the fresh water’s ionic strength when no conductivity is measured.')),
    _parameter('co2_mg_l', _('Carbon dioxide (mg/L free CO₂)'), _('CO₂ (mg/L)'), 1, 0, 200, 'acid',
               _('Free carbon dioxide, from a CO₂ probe or a titration.')),
    _parameter('tan_mg_l', _('Total ammonia nitrogen (mg/L TAN as N)'), _('TAN (mg/L N)'), 3, 0, 100,
               'nitrogen', _('NH₃ and NH₄⁺ together, as nitrogen. A kit that reads NH₄⁺: divide by 1.29; one that '
                             'reads NH₃: divide by 1.22. The toxic NH₃ is worked out from this, the pH and the '
                             'temperature of the same sample.')),
    _parameter('nitrite_n_mg_l', _('Nitrite (mg/L NO₂ as N)'), _('NO₂-N (mg/L)'), 3, 0, 100, 'nitrogen',
               _('As nitrogen. A kit that reads NO₂⁻: divide by 3.29.')),
    _parameter('nitrate_n_mg_l', _('Nitrate (mg/L NO₃ as N)'), _('NO₃-N (mg/L)'), 1, 0, 1000, 'nitrogen',
               _('As nitrogen. A kit that reads NO₃⁻: divide by 4.43.')),
    _parameter('tgp_pct', _('Total gas pressure (% of barometric pressure)'), _('TGP (%)'), 1, 50, 200, 'other',
               _('From a saturometer (total dissolved gas).')),
    _parameter('salinity_ppt', _('Salinity (‰, g/kg)'), _('Salinity (‰)'), 1, 0, 50, 'other',
               _('PSU is the same number: 0 in fresh water, about 35 in the sea.')),
    _parameter('conductivity_25_us_cm', _('Conductivity at 25 °C (µS/cm, temperature-compensated)'),
               _('EC 25 °C (µS/cm)'), 0, 0, 100000, 'other',
               _('Specific conductance: the meter’s reading compensated to 25 °C (the meter’s temperature compensation '
                 'on, referred to 25 °C, not 20 °C). A reading at the water’s own temperature is not this value. In '
                 'fresh water the ionic strength is taken from it (Russell 1976).')),
    _parameter('turbidity_ntu', _('Turbidity (NTU)'), _('Turbidity (NTU)'), 1, 0, 4000, 'other'),
]

# Worked out on read from the same sample (farm/water/chemistry.py), never stored. NH₃-N takes limits;
# NH₄-N is shown only. Their range is TAN's.
NH3_N = _parameter('nh3_n_mg_l', _('Un-ionised ammonia (mg/L NH₃ as N)'), _('NH₃-N (mg/L)'), 4, 0, 100,
                   measured=False)
NH4_N = _parameter('nh4_n_mg_l', _('Ammonium (mg/L NH₄⁺ as N)'), _('NH₄-N (mg/L)'), 3, 0, 100, measured=False)

BY_CODE = {parameter.code: parameter for parameter in (*MEASURED, NH3_N, NH4_N)}
COLUMNS = [parameter.code for parameter in MEASURED]
# What a limit can be set on: every measured parameter, and the toxic ammonia worked out from TAN.
LIMITED = [*MEASURED, NH3_N]
LIMIT_CHOICES = [(parameter.code, parameter.label) for parameter in LIMITED]

TEMPERATURE, SALINITY, PH, TAN = 'temperature_c', 'salinity_ppt', 'ph', 'tan_mg_l'
OXYGEN_MG_L, OXYGEN_PCT = 'oxygen_mg_l', 'oxygen_saturation_pct'
# One quantity in two units: a limit row on either judges it (the oxygen: mg/L and % of air saturation are one reading,
# farm/water/read.py), so a value of one with no row of its own is not "unjudged" while the other has one.
SAME_QUANTITY = {OXYGEN_MG_L: OXYGEN_PCT, OXYGEN_PCT: OXYGEN_MG_L}


def get(code):
    return BY_CODE[code]


def in_group(key):
    return [parameter for parameter in MEASURED if parameter.group == key]
