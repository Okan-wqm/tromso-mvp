"""Binding a channel to where its values belong, the only way a binding's history grows. History is never rewritten: a
moment in the future, or before a channel's open binding started, is refused. The database holds the rest (sensors
migrations 0004 and 0007).

- `move` closes one channel's open binding at a moment and opens the next one there, `unbind` closes it: one
  transaction, one activity-log entry on the channel ("Bound to", from the old target to the new).
- `move_device` moves a whole device (a portable probe taken to another tank, pond, cage or system, maybe at another
  site) from one moment: every live channel that is not retired goes to the place its kind goes to at the target
  (`landing`), a retired or deleted channel's open binding just ends; all or nothing, refused with each channel's reason
  (`plan_device` says the same beforehand). One entry on the device's log lists every channel's old and new place, and
  each channel's own log says it too. The device's site follows it: a device is at one site at a time, the site of the
  places it is bound to (the database refuses a channel bound alone at another site, and a placed device's site changed
  by hand).
  `unbind_device` takes the device out of the water (storage, calibration): its readings are still stored, and belong
  to no place until it is placed again.
- `clock`: the clock a moment of a binding is typed and shown on: the place's site, else the device's.

The rules a move checks are in one place, `refusals`: the kind of place a channel's quantity goes to (owner rule A1),
one primary and one backup per place and quantity, a channel moved alone stays at its device's site."""
from dataclasses import dataclass
from itertools import groupby

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone
from django.utils.translation import gettext as _, gettext_lazy

from core import audit
from core.models import AuditLog
from farm.models import Equipment, SamplingPoint, System, Tank
from farm.models.site import zone_of
from farm.models.water_point import site_of
from farm.water.read import middle_points

from .models import Binding, Channel, ChannelStatus, Device

LABEL = 'Bound to'
SITE_LABEL = 'Site'
KINDS = {SamplingPoint: 'point', System: 'system', Equipment: 'equipment'}
WATER_PLACES = gettext_lazy('A water value is bound to a sampling point or a system.')
PROCESS_PLACES = gettext_lazy('A process value is bound to a piece of equipment or a system.')


def _target_label(binding):
    if binding is None:
        return None
    return f'{binding.target} ({binding.get_role_display()})'


def kind_of(place):
    """'point', 'system' or 'equipment': the column of a binding that holds `place`."""
    return KINDS[type(place)]


def clock(device, place=None):
    """The clock a moment of the device's binding is typed and shown on: the site of the place (a unit, a sampling point,
    a system or a piece of equipment), else the device's own (a department without a site, or no place). A placed
    device's site is its place's, so the two agree while it is placed."""
    site = site_of(place) if place is not None else None
    return zone_of(site or device.site)


def _open(channel, lock=True):
    found = Binding.objects.filter(channel=channel, valid_to__isnull=True)
    return (found.select_for_update() if lock else found).first()


def _moment_refusal(at, current):
    if at > timezone.now():
        return _('A binding cannot start in the future.')
    if current is not None and at <= current.valid_from:
        return _('The channel is bound since %(moment)s: a move starts after that.') % {
            'moment': timezone.localtime(current.valid_from, clock(current.channel.device, current.target))
            .strftime('%Y-%m-%d %H:%M')}
    return ''


def _check_moment(at, current):
    refusal = _moment_refusal(at, current)
    if refusal:
        raise ValidationError({'valid_from': refusal})


def refusals(channel, place, role, at, moving=(), alone=True):
    """[(field, message)]: why `channel` cannot be bound to `place` (a sampling point, a system or a piece of equipment)
    as `role` from `at`. `moving`: the channels moved with it, whose bindings end then; `alone`: the channel moves without
    its device, so it stays at its device's site."""
    kind = kind_of(place)
    if channel.is_water and kind == 'equipment':
        return [('target', WATER_PLACES)]
    if not channel.is_water and kind == 'point':
        return [('target', PROCESS_PLACES)]
    found = []
    site = site_of(place)
    if alone and site is not None and site.pk != channel.device.site_id:
        found.append(('target', _('%(device)s is at %(site)s: a channel goes to another site with its whole device '
                                  '(Move device).') % {'device': channel.device, 'site': channel.device.site}))
    clash = (Binding.objects.filter(**{kind: place}, role=role, channel__quantity=channel.quantity)
             .exclude(channel__in=[channel.pk, *[each.pk for each in moving]])
             .filter(Q(valid_to__isnull=True) | Q(valid_to__gt=at)).select_related('channel__device').first())
    if clash is not None:
        found.append(('role', _('%(target)s already has a %(role)s %(quantity)s channel then: %(channel)s.') % {
            'target': place, 'role': clash.get_role_display().lower(), 'quantity': channel.quantity_info.label,
            'channel': clash.channel}))
    return found


def _close(user, binding, at):
    binding.valid_to = at
    binding.version += 1
    binding.updated_by = user
    binding.save(update_fields=['valid_to', 'version', 'updated_by', 'updated_at'])


def _start(user, channel, at, role, note, place):
    return Binding.objects.create(channel=channel, role=role, valid_from=at, note=note, created_by=user,
                                  updated_by=user, **{kind_of(place): place})


def _record_channel(user, channel, before, after):
    with audit.source_language():
        audit.record(user, AuditLog.Action.UPDATE, channel, {LABEL: [_target_label(before), _target_label(after)]})


def move(user, channel, at, role=Binding.Role.PRIMARY, note='', **target):
    """Binds `channel` from `at` to one target (point=, system= or equipment=), closing its open binding there. Returns the
    new binding."""
    (place,) = target.values()
    with transaction.atomic():
        channel = Channel.objects.select_for_update().select_related('device__site').get(pk=channel.pk)
        current = _open(channel)
        _check_moment(at, current)
        refused = refusals(channel, place, role, at)
        if refused:
            raise ValidationError({field: message for field, message in refused})
        if current is not None:
            _close(user, current, at)
        binding = _start(user, channel, at, role, note, place)
        _record_channel(user, channel, current, binding)
    return binding


def unbind(user, channel, at):
    """Ends the channel's open binding at `at`; nothing to end is said."""
    with transaction.atomic():
        channel = Channel.objects.select_for_update().get(pk=channel.pk)
        current = _open(channel)
        if current is None:
            raise ValidationError(_('The channel is not bound anywhere now.'))
        _check_moment(at, current)
        _close(user, current, at)
        _record_channel(user, channel, current, None)
    return current


# ---- a whole device ----------------------------------------------------------------------------------------
@dataclass
class Step:
    """What a device move does to one channel: from its open binding (`current`) to `place` (None: nowhere), or why it
    cannot (`reason`)."""
    channel: Channel
    current: Binding | None
    place: object = None
    reason: str = ''
    binding: Binding | None = None

    @property
    def moves(self):
        """The channel is bound at the target (a live channel that is not retired)."""
        return not self.channel.is_deleted and self.channel.state != ChannelStatus.RETIRED


def landing(channel, target):
    """(place, '') where the channel goes at `target`, or (None, why not): a water value to a unit's middle point, the
    sampling point chosen or the system; a process value to the system, the piece of equipment, or the system or piece
    of equipment a sampling point is on."""
    if isinstance(target, Tank):
        if not channel.is_water:
            return None, PROCESS_PLACES
        point = middle_points([target]).get(target.pk)
        return (point, '') if point is not None else (None, _('%(unit)s has no middle sampling point.') % {
            'unit': target})
    if isinstance(target, SamplingPoint):
        if channel.is_water:
            return target, ''
        owner = target.owner
        return (owner, '') if isinstance(owner, (System, Equipment)) else (None, PROCESS_PLACES)
    if isinstance(target, System):
        return target, ''
    if isinstance(target, Equipment):
        return (None, WATER_PLACES) if channel.is_water else (target, '')
    raise TypeError(f'A device is not placed at {type(target).__name__}')


def _plan(device, channels, target, at, role, lock):
    steps = [Step(channel, _open(channel, lock)) for channel in channels]
    moving = [step.channel for step in steps]
    taken = {}
    for step in steps:
        refusal = _moment_refusal(at, step.current) if step.current is not None or step.moves else ''
        if refusal:
            step.reason = refusal
            continue
        if target is None or not step.moves:
            continue
        step.place, step.reason = landing(step.channel, target)
        if step.place is None:
            continue
        refused = refusals(step.channel, step.place, role, at, moving=moving, alone=False)
        key = (kind_of(step.place), step.place.pk, step.channel.quantity)
        if not refused and key in taken:
            refused = [('role', _('%(channel)s measures %(quantity)s as %(other)s does: one of the two is the backup '
                                  'there.') % {'channel': step.channel.code, 'other': taken[key].code,
                                               'quantity': step.channel.quantity_info.label})]
        taken.setdefault(key, step.channel)
        step.reason = ' '.join(str(message) for _field, message in refused)
    return steps


def _channels(device, lock):
    found = Channel.all_objects.filter(device=device).select_related('device__site').order_by('code')
    return list(found.select_for_update(of=('self',)) if lock else found)


def plan_device(device, target, at, role=Binding.Role.PRIMARY):
    """[Step] of moving the device to `target` (a unit, a sampling point, a system or a piece of equipment; None: out of
    the water) from `at`, without moving anything: the dialog shows it before the move."""
    return [step for step in _plan(device, _channels(device, lock=False), target, at, role, lock=False)
            if step.moves or step.current is not None]


def move_device(user, device, at, target, role=Binding.Role.PRIMARY, note=''):
    """Moves every channel of the device from `at` to `target` (None: out of the water, `unbind_device`), all or nothing.
    Returns the steps."""
    with transaction.atomic():
        device = Device.objects.select_for_update(of=('self',)).select_related('site').get(pk=device.pk)
        steps = [step for step in _plan(device, _channels(device, lock=True), target, at, role, lock=True)
                 if step.moves or step.current is not None]
        refused = [f'{step.channel.code}: {step.reason}' for step in steps if step.reason]
        if refused:
            raise ValidationError(refused)
        if target is None and not any(step.current for step in steps):
            raise ValidationError(_('The device is not placed anywhere now.'))
        if target is not None and not any(step.moves for step in steps):
            raise ValidationError(_('The device has no channel to place.'))
        for step in steps:
            if step.current is not None:
                _close(user, step.current, at)
        changes = {}
        site = site_of(target) if target is not None else None
        if site is not None and site.pk != device.site_id:
            # Every open binding is closed now: the database lets the site move, then takes the new ones there.
            changes[SITE_LABEL] = [str(device.site), str(site)]
            Device.objects.filter(pk=device.pk).update(site=site, version=device.version + 1, updated_by=user,
                                                       updated_at=timezone.now())
        for step in steps:
            if step.place is not None:
                step.binding = _start(user, step.channel, at, role, note, step.place)
            if step.current is not None or step.binding is not None:
                _record_channel(user, step.channel, step.current, step.binding)
                changes[f'{LABEL} ({step.channel.code})'] = [_target_label(step.current), _target_label(step.binding)]
        with audit.source_language():
            audit.record(user, AuditLog.Action.UPDATE, device, changes)
    return steps


def unbind_device(user, device, at):
    """Takes the device out of the water from `at`: every open binding of its channels ends then."""
    return move_device(user, device, at, None)


# ---- where devices are -------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Stay:
    """A time a device's channels were bound somewhere: from `start` until `end` (None: now), at `places`."""
    start: object
    end: object
    places: list


def _visible_of(devices):
    return (Binding.objects.visible().filter(channel__device__in=devices)
            .select_related('channel', 'point__unit', 'point__system', 'point__equipment', 'system', 'equipment'))


def _distinct(bindings):
    places = []
    for binding in bindings:
        if binding.target not in places:
            places.append(binding.target)
    return places


def placed(now=None):
    """The condition, over devices, "its channels are bound somewhere now" (a device not placed is out of the water)."""
    return Exists(Binding.objects.visible().at(now or timezone.now()).filter(channel__device=OuterRef('pk')))


def holds_site(device):
    """Whether the device's site is held by where it is: an open live binding of any of its channels, a deleted one's
    too (the rule migration 0007 holds; the pages leave a deleted channel's binding out of sight). Its site changes then
    only by a move."""
    return Binding.objects.filter(channel__device=device, valid_to__isnull=True).exists()


def placements(devices, now=None):
    """{device id: [place]}: where each device's channels are bound now (empty: not placed)."""
    devices = list(devices)
    found = {device.pk: [] for device in devices}
    bindings = sorted(_visible_of(devices).at(now or timezone.now()), key=lambda binding: binding.channel.code)
    for binding in bindings:
        if binding.target not in found[binding.channel.device_id]:
            found[binding.channel.device_id].append(binding.target)
    return found


def placement_history(device):
    """[Stay] of the device, newest first: its channels' bindings grouped by the time they held."""
    bindings = sorted(_visible_of([device]), key=lambda binding: (binding.valid_from, binding.valid_to is None,
                                                                  binding.valid_to or binding.valid_from), reverse=True)
    return [Stay(start, end, _distinct(group))
            for (start, end), group in groupby(bindings, key=lambda binding: (binding.valid_from, binding.valid_to))]
