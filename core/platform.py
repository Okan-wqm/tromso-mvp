"""The platform owner's settings as the rest of the code reads them (core.models.PlatformSettings): the one place each is
read, so a rule that depends on one cannot read it its own way.

- `correction_window_days()`: how far back a daily record may be dated and how old a record may be voided (farm/stock/
  dates.py applies it; every message that names the days reads it here);
- `second_approval_required(kind)`: whether an acknowledgement of that kind waits for a second person (the kinds are
  APPROVALS); the hook of the withdrawal acknowledgement calls it with 'withdrawal';
- `escalation_after()`: how long an alarm waits for an acknowledgement before the next people are notified.

Inside a request the row is read once (PlatformSettingsMiddleware opens the memo, saving the row drops it): a page asks
for the window once per row it lists, and its queries must not grow with its rows. Outside a request (a command, the
alarm loop) every call reads the row."""
from contextvars import ContextVar
from datetime import timedelta

# The acknowledgements a second person may be asked to approve: {kind: the setting's column}.
APPROVALS = {'withdrawal': 'second_approval_withdrawal'}

_memo = ContextVar('platform_settings', default=None)


def current():
    """The settings row; inside a request, the one read first in it."""
    from .models import PlatformSettings
    held = _memo.get()
    if held is None:
        return PlatformSettings.get()
    if 'row' not in held:
        held['row'] = PlatformSettings.get()
    return held['row']


def open_memo():
    """Starts a request's memo; returns the token `close_memo` takes."""
    return _memo.set({})


def close_memo(token):
    _memo.reset(token)


def forget():
    """Drops the memo's row (it was just saved): the next read in this request reads it again."""
    held = _memo.get()
    if held is not None:
        held.pop('row', None)


def correction_window_days():
    """How many days back a daily record may be dated, and how old a record may be voided."""
    return current().correction_window_days


def second_approval_required(kind):
    """Whether an acknowledgement of `kind` (one of APPROVALS) must be approved by a second person before what it was
    given for counts. An unknown kind is a programming error, never a quiet no."""
    if kind not in APPROVALS:
        raise ValueError(f'No second-approval setting for {kind!r}: one of {sorted(APPROVALS)}.')
    return getattr(current(), APPROVALS[kind])


def escalation_after():
    """How long an alarm waits for an acknowledgement before the next people are notified."""
    return timedelta(minutes=current().alarm_escalation_minutes)
