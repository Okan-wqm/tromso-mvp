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


@register.simple_tag
def placed_and_clock(devices):
    """[(device, [place], clock note or '')] of the page's devices: `placed`, and for a device whose clock is past the
    alarm rules' warning limit now, the note saying how far (alarms/clock.py, the alarm's own judgement)."""
    from django.utils import timezone

    from alarms import clock
    rows = placed(devices)
    notes = clock.notes([device.pk for device, _places in rows], timezone.now()) if rows else {}
    return [(device, places, notes.get(device.pk, '')) for device, places in rows]
