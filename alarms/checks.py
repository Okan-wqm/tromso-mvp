"""The alarms' deployment check (`manage.py check --deploy`, and so CI and a release): settings.ALARM_TRANSPORTS is a
{channel: dotted path} dictionary whose keys are notification channels (alarms.models.Channel; landing review 5, N8),
and every transport named in it imports, is a Transport, and declares `max_bytes`, a whole number of at least 1
(REVIEW4: a transport without a limit sends nothing, and that would only show at the first real alarm, perhaps at
night).

A deployment check only, never an ordinary one: Django runs the ordinary checks before every management command, so one
wrong transport setting at Error level would stop `manage.py run_alarm_worker`, and no alarm would be checked at all.

And one database check (`manage.py check --database default`, never on its own): alarms.W001, the open alarms' queue
against the clearances."""
from django.conf import settings
from django.core.checks import Error, Tags, Warning, register
from django.utils.module_loading import import_string

from .models import Channel
from .transports import Transport

SHOWN = 20         # alarm ids a warning of alarms.W001 names; the rest are counted


@register(deploy=True)
def transports_declare_limits(app_configs, **kwargs):
    errors = []
    setting = getattr(settings, 'ALARM_TRANSPORTS', None) or {}
    if not isinstance(setting, dict):
        return [Error(f'ALARM_TRANSPORTS is a {type(setting).__name__}, not a dictionary: no alarm would be sent.',
                      hint='Give {channel: dotted path of a Transport class}, or {} while none is connected.',
                      id='alarms.E004')]
    for channel, path in sorted(setting.items(), key=lambda pair: repr(pair[0])):
        if channel not in Channel.values:
            errors.append(Error(f'ALARM_TRANSPORTS names {channel!r}, which is not a notification channel: its '
                                f'transport would never be used.',
                                hint=f'The channels are: {", ".join(Channel.values)}.', id='alarms.E005'))
            continue
        try:
            made = import_string(path)
        except Exception as error:
            errors.append(Error(f'ALARM_TRANSPORTS[{channel!r}] = {path!r} cannot be imported: {error}.',
                                hint='Name the dotted path of a Transport class.', id='alarms.E001'))
            continue
        if not (isinstance(made, type) and issubclass(made, Transport)):
            errors.append(Error(f'ALARM_TRANSPORTS[{channel!r}] = {path!r} is not a Transport (alarms/transports.py).',
                                id='alarms.E002'))
            continue
        limit = getattr(made, 'max_bytes', None)
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            errors.append(Error(f'The {channel} transport {path} declares no max_bytes (a whole number of at least 1, '
                                f'its service’s limit in UTF-8 bytes): it would send nothing.', id='alarms.E003'))
    return errors


@register(Tags.database)
def open_alarms_hold(app_configs, **kwargs):
    """The open alarms' queue (`alarm_open`, alarms 0025) is exactly the alarms without a clearance, both ways: an open
    alarm missing from it is never notified, escalated or listed; a cleared one left in it is reminded after it
    cleared. The triggers keep it so whoever writes; what passes them by is a superuser's (a TRUNCATE of one table,
    `session_replication_role = replica`, a trigger disabled, a hand repair), and this finds it. Read-only, a scan at
    check time, never in a pass. Run with `manage.py check --database default` (after migrate, after a restore); quiet
    until 0025 has run."""
    from django.db import DatabaseError, connection
    from django.db.migrations.recorder import MigrationRecorder
    try:
        if ('alarms', '0025_open_alarms') not in MigrationRecorder(connection).applied_migrations():
            return []
        with connection.cursor() as cursor:
            cursor.execute('SELECT a.id FROM alarms a WHERE NOT EXISTS (SELECT 1 FROM alarm_clearances c '
                           'WHERE c.alarm_id = a.id) AND NOT EXISTS (SELECT 1 FROM alarm_open o WHERE o.alarm_id = a.id) '
                           'ORDER BY a.id')
            missing = [row[0] for row in cursor.fetchall()]
            cursor.execute('SELECT o.alarm_id FROM alarm_open o JOIN alarm_clearances c ON c.alarm_id = o.alarm_id '
                           'ORDER BY o.alarm_id')
            cleared = [row[0] for row in cursor.fetchall()]
    except DatabaseError:
        return []
    found = []
    if missing:
        found.append(Warning(
            f'{len(missing)} open alarm(s) are missing from the open alarms\' queue (alarm_open), so they are never '
            f'notified, escalated or listed: {_ids(missing)}.',
            hint='As the database\'s owner role: INSERT INTO alarm_open (alarm_id) SELECT a.id FROM alarms a WHERE NOT '
                 'EXISTS (SELECT 1 FROM alarm_clearances c WHERE c.alarm_id = a.id) ON CONFLICT DO NOTHING;',
            id='alarms.W001'))
    if cleared:
        found.append(Warning(
            f'{len(cleared)} cleared alarm(s) are still in the open alarms\' queue (alarm_open), so they are reminded and '
            f'escalated after they cleared: {_ids(cleared)}.',
            hint='As the database\'s owner role: DELETE FROM alarm_open o USING alarm_clearances c WHERE c.alarm_id = '
                 'o.alarm_id;', id='alarms.W001'))
    return found


def _ids(ids):
    return ', '.join(str(each) for each in ids[:SHOWN]) + (f' and {len(ids) - SHOWN} more' if len(ids) > SHOWN else '')
