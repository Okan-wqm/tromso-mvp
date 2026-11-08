"""Where devices are, for a list page: one read for the page's devices (sensors/bindings.py `placements`)."""
from django import template

from sensors import bindings

register = template.Library()


@register.simple_tag
def placed(devices):
    """[(device, [place])] of the page's devices, in their order: where each is bound now (empty: not placed)."""
    devices = list(devices)
    found = bindings.placements(devices)
    return [(device, found[device.pk]) for device in devices]
