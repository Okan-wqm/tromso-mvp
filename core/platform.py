"""The platform owner's settings as the rest of the code reads them (core.models.PlatformSettings): the one place each is
read, so a rule that depends on one cannot read it its own way.

- `correction_window_days()`: how far back a daily record may be dated and how old a record may be voided (farm/stock/
  dates.py applies it; every message that names the days reads it here), and `window_way_out()`, the sentence every
  refusal by the window ends with: whose setting it is and where it is changed;
- `plan_batch_cells()`: how many days of the shift schedule one paint may plan (hr.services.plan_shifts);
- `second_approval_required(kind)`: whether an acknowledgement of that kind waits for a second person (the kinds are
  APPROVALS); the hook of the withdrawal acknowledgement calls it with 'withdrawal';

Inside a request the row is read once (PlatformSettingsMiddleware opens the memo, saving the row drops it): a page asks
for the window once per row it lists, and its queries must not grow with its rows. Outside a request (a command, the
alarm loop) every call reads the row."""
from contextvars import ContextVar

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


def plan_batch_cells():
    """How many days of the shift schedule may be planned in one go (one request's bound)."""
    return current().plan_batch_cells


def unknown_withdrawal_days():
    """How many days after a course's last day a medicine withdrawal whose end is unknown holds fish."""
    return current().unknown_withdrawal_days


def degree_day_rules():
    """The degree-days' rules as farm/water/degree_days.py reads them, in one read of the row: (the hours of a day that
    must hold a good reading before a probe's day counts, the seconds one reading stands for the water, the measured
    days before a gap that cap an assumed temperature, the °C a probe's day and the day's samples may differ before it
    is said)."""
    row = current()
    return row.sensor_day_hours, row.sensor_hold_seconds, row.assumption_cap_days, row.probe_sample_tolerance_c


def window_way_out():
    """What to do about a record older than the correction window, said with every refusal by the window (flow fault
    B-07: "Operations can be dated at most 31 days back." was a dead end): whose setting the window is and where it is
    changed, by the menu's own names, so the sentence follows the menu."""
    from django.utils.translation import gettext as _

    from . import navigation
    return _('The correction window is the platform owner’s setting: it is changed in %(where)s.') % {
        'where': navigation.trail('core.view_platformsettings', _('Platform settings'))}


def second_approval_required(kind):
    """Whether an acknowledgement of `kind` (one of APPROVALS) must be approved by a second person before what it was
    given for counts. An unknown kind is a programming error, never a quiet no."""
    if kind not in APPROVALS:
        raise ValueError(f'No second-approval setting for {kind!r}: one of {sorted(APPROVALS)}.')
    return getattr(current(), APPROVALS[kind])

