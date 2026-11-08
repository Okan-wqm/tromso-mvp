"""How a sensor's value reads on the page: at its quantity's decimals (sensors/quantities.py, a water parameter's own), digits
grouped as the language writes them, the one rule the water pages follow too (farm/templatetags/water.py `water_value`)."""
from django import template

from farm.templatetags.stock import DASH, number

from .. import quantities

register = template.Library()


@register.filter
def measured(value, code):
    """13.0 °C, 45.4 mg/L, 1,520 µS/cm: `value` of the quantity `code`."""
    if value in (None, ''):
        return DASH
    return number(value, quantities.get(code).decimals)
