"""Temperature profiles' own acts: Duplicate (a draft copy with its points, logged as created), and what a profile gives
over the fish's weight, for its page (`used`): read by the very function the plan ahead reads (ration.Profile.at), so
the page cannot show another rule."""
from dataclasses import dataclass
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext as _, gettext_lazy

from core import access, audit
from farm.models import TemperatureProfile, TemperatureProfilePoint
from farm.models.assignment import ProtocolStatus

from . import read

ADD = 'farm.add_temperatureprofile'
POINTS = gettext_lazy('Points')
COPIED = ('species', 'temperature_between', 'notes')


def describe(profile):
    """The points as the activity log keeps them: "50 g 12 °C; 200 g 14 °C"; None without points."""
    return '; '.join(f'{point.weight_g.normalize():f} g {point.temperature_c.normalize():f} °C'
                     for point in profile.points.order_by('weight_g')) or None


def copy_name(name):
    """The first free name of a copy: "Smolt RAS (copy)", then "(copy 2)" and so on."""
    import re
    base = re.sub(r' \(copy(?: \d+)?\)$', '', name)
    taken = {item.lower() for item in TemperatureProfile.objects.values_list('name', flat=True)}
    for number in range(1, 1000):
        candidate = f'{base} (copy)' if number == 1 else f'{base} (copy {number})'
        if candidate.lower() not in taken and len(candidate) <= TemperatureProfile._meta.get_field('name').max_length:
            return candidate
    raise ValidationError(_('Rename the profile first: its copies have used every name.'))


def duplicate(user, profile, snapshot):
    """A draft copy of the profile and its points, to change and assign from a date; logged as created."""
    access.require(user, ADD)
    with transaction.atomic():
        source = TemperatureProfile.objects.get(pk=profile.pk)
        copy = TemperatureProfile(name=copy_name(source.name), status=ProtocolStatus.DRAFT, created_by=user,
                                  updated_by=user, **{name: getattr(source, name) for name in COPIED})
        copy.full_clean()
        copy.save()
        TemperatureProfilePoint.objects.bulk_create([
            TemperatureProfilePoint(profile=copy, weight_g=point.weight_g, temperature_c=point.temperature_c,
                                    created_by=user) for point in source.points.all()])
        with audit.source_language():
            audit.record_create(user, copy, {**snapshot(copy), str(POINTS): describe(copy)})
        return copy


@dataclass(frozen=True)
class Used:
    """The temperature a profile gives fish of `weight_g`; `point`: the weight is one of its points (the value
    entered), else it is half way between two of them."""
    weight_g: Decimal
    temperature_c: Decimal
    point: bool


def used(profile):
    """[Used] at every point of a stored profile and half way between two neighbouring points, in weight order."""
    if profile is None or profile.pk is None:
        return []
    found = read.profiles([profile])[profile.pk]
    if not found.points:
        return []
    weights = [weight for weight, _value in found.points]
    between = [(low + high) / 2 for low, high in zip(weights, weights[1:])]
    return [Used(weight, found.at(weight), weight in weights) for weight in sorted(set(weights) | set(between))]
