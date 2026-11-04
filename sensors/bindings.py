"""Binding a channel to where its values belong, the only way a binding's history grows: `move` closes the channel's open
binding at a moment and opens the next one there, `unbind` closes it. One transaction, one activity-log entry on the
channel ("Bound to", from the old target to the new). A moment in the future, or before the open binding started, is
refused: history is never rewritten. The database holds the rest (sensors migration 0004)."""
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from core import audit
from core.models import AuditLog

from .models import Binding, Channel

LABEL = 'Bound to'


def _target_label(binding):
    if binding is None:
        return None
    return f'{binding.target} ({binding.get_role_display()})'


def _open(channel):
    return Binding.objects.select_for_update().filter(channel=channel, valid_to__isnull=True).first()


def _check_moment(at, current):
    if at > timezone.now():
        raise ValidationError({'valid_from': _('A binding cannot start in the future.')})
    if current is not None and at <= current.valid_from:
        raise ValidationError({'valid_from': _('The channel is bound since %(moment)s: a move starts after that.')
                               % {'moment': timezone.localtime(current.valid_from).strftime('%Y-%m-%d %H:%M')}})


def _close(user, binding, at):
    binding.valid_to = at
    binding.version += 1
    binding.updated_by = user
    binding.save(update_fields=['valid_to', 'version', 'updated_by', 'updated_at'])


def move(user, channel, at, role=Binding.Role.PRIMARY, note='', **target):
    """Binds `channel` from `at` to one target (point=, system= or equipment=), closing its open binding there. Returns the
    new binding."""
    with transaction.atomic():
        channel = Channel.objects.select_for_update().get(pk=channel.pk)
        current = _open(channel)
        _check_moment(at, current)
        if current is not None:
            _close(user, current, at)
        binding = Binding.objects.create(channel=channel, role=role, valid_from=at, note=note, created_by=user,
                                         updated_by=user, **target)
        with audit.source_language():
            audit.record(user, AuditLog.Action.UPDATE, channel,
                         {LABEL: [_target_label(current), _target_label(binding)]})
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
        with audit.source_language():
            audit.record(user, AuditLog.Action.UPDATE, channel, {LABEL: [_target_label(current), None]})
    return current
