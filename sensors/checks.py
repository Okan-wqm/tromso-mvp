"""The sensors' checks of the database (`manage.py check --database default`, as core.W003 and core.W004)."""
from django.core.checks import Tags, Warning, register

# How many channels the warning names; the rest are counted.
NAMED = 10


@register(Tags.database)
def uncovered_channels(app_configs, **kwargs):
    """The channels of a quantity the water limits judge that no active "No fresh value" rule covers (sensors/alarms.py
    `uncovered`: its default rule switched off, with its reason, and no rule of the channel's own; never the dissolved
    oxygen's, which the alarm system says for a unit with fish all the same): a probe of theirs that stops sending
    raises no alarm of its own. Listed for the alarm admin to review; nothing is changed."""
    from django.db import DatabaseError

    from .alarms import uncovered
    try:
        found = uncovered()
    except DatabaseError:
        return []
    if not found:
        return []
    named = ', '.join(f'{channel} ({channel.get_quantity_display()})' for channel in found[:NAMED])
    more = f' and {len(found) - NAMED} more' if len(found) > NAMED else ''
    return [Warning(
        f'{len(found)} channel(s) of a water quantity the limits judge have no active "No fresh value" rule: {named}'
        f'{more}. A probe of theirs that stops sending raises no alarm of its own (the dissolved oxygen is not listed: '
        f'a unit with fish whose oxygen has no fresh value is a critical alarm all the same).',
        hint='Switch the quantity\'s default rule on again in Sensors › Alarm rules, or give the channel a "No fresh '
             'value" rule of its own.', id='sensors.W001')]
