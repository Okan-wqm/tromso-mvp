"""The alarms' deployment check (`manage.py check --deploy`, and so CI and a release): settings.ALARM_TRANSPORTS is a
{channel: dotted path} dictionary whose keys are notification channels (alarms.models.Channel; landing review 5, N8),
and every transport named in it imports, is a Transport, and declares `max_bytes`, a whole number of at least 1
(REVIEW4: a transport without a limit sends nothing, and that would only show at the first real alarm, perhaps at
night).

A deployment check only, never an ordinary one: Django runs the ordinary checks before every management command, so one
wrong transport setting at Error level would stop `manage.py run_alarm_worker`, and no alarm would be checked at all.

And two database checks (`manage.py check --database default`, never on their own): alarms.W001, the open alarms'
queue against the clearances, and alarms.W002, the sensor events' queue still to mirror against the alarms."""
from django.conf import settings
from django.core.checks import Error, Tags, Warning, register
from django.utils.module_loading import import_string

from .models import Channel
from .transports import Transport

SHOWN = 20         # ids a warning of alarms.W001 or W002 names; the rest are counted


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
    cleared."""
    def scan(cursor):
        cursor.execute('SELECT a.id FROM public.alarms a WHERE NOT EXISTS (SELECT 1 FROM public.alarm_clearances c '
                       'WHERE c.alarm_id = a.id) AND NOT EXISTS (SELECT 1 FROM public.alarm_open o WHERE '
                       'o.alarm_id = a.id) ORDER BY a.id')
        missing = [row[0] for row in cursor.fetchall()]
        cursor.execute('SELECT o.alarm_id FROM public.alarm_open o JOIN public.alarm_clearances c ON c.alarm_id = '
                       'o.alarm_id ORDER BY o.alarm_id')
        return missing, [row[0] for row in cursor.fetchall()]
    return _queue_holds('0025_open_alarms', scan, 'alarms.W001', missing=(
        "open alarm(s) are missing from the open alarms' queue (alarm_open), so they are never notified, escalated or "
        'listed',
        'INSERT INTO alarm_open (alarm_id) SELECT a.id FROM alarms a WHERE NOT EXISTS (SELECT 1 FROM alarm_clearances c '
        'WHERE c.alarm_id = a.id) ON CONFLICT DO NOTHING;'), stale=(
        "cleared alarm(s) are still in the open alarms' queue (alarm_open), so they are reminded and escalated after "
        'they cleared',
        'DELETE FROM alarm_open o USING alarm_clearances c WHERE c.alarm_id = o.alarm_id;'))


@register(Tags.database)
def unmirrored_events_hold(app_configs, **kwargs):
    """The sensor events' queue still to mirror (`alarm_unmirrored_events`, alarms 0026) is exactly the sensor alarm
    events no alarm mirrors, both ways: an event missing from it never becomes an alarm, so nobody is told of it; a
    mirrored one left in it is read by every pass and passed over (alarms/sources.py `sensor_events`)."""
    def scan(cursor):
        cursor.execute('SELECT e.id FROM public.sensors_alarm_event e WHERE NOT EXISTS (SELECT 1 FROM public.alarms a '
                       'WHERE a.sensor_event_id = e.id) AND NOT EXISTS (SELECT 1 FROM public.alarm_unmirrored_events u '
                       'WHERE u.event_id = e.id) ORDER BY e.id')
        missing = [row[0] for row in cursor.fetchall()]
        cursor.execute('SELECT u.event_id FROM public.alarm_unmirrored_events u JOIN public.alarms a ON '
                       'a.sensor_event_id = u.event_id ORDER BY u.event_id')
        return missing, [row[0] for row in cursor.fetchall()]
    return _queue_holds('0026_unmirrored_events', scan, 'alarms.W002', missing=(
        'sensor alarm event(s) without an alarm are missing from the queue of events to mirror '
        '(alarm_unmirrored_events), so they never become alarms and nobody is told',
        'INSERT INTO alarm_unmirrored_events (event_id) SELECT e.id FROM sensors_alarm_event e WHERE NOT EXISTS (SELECT '
        '1 FROM alarms a WHERE a.sensor_event_id = e.id) ON CONFLICT DO NOTHING;'), stale=(
        'sensor alarm event(s) an alarm mirrors already are still in the queue of events to mirror '
        '(alarm_unmirrored_events), read by every pass of the alarm worker',
        'DELETE FROM alarm_unmirrored_events u USING alarms a WHERE a.sensor_event_id = u.event_id;'))


def _queue_holds(migration, scan, check, missing, stale):
    """A queue the database keeps by its triggers (core.operations.DefinerTrigger) against what it stands for, both
    ways: `scan(cursor)` gives (the ids missing from it, the ids it holds wrongly); `missing` and `stale` are each
    (what the warning says, the repair). The triggers keep it whoever writes; what passes them by is a superuser's (a
    TRUNCATE of one table, `session_replication_role = replica`, a trigger disabled, a hand repair) or raw SQL by an
    explicit id while the row it names is uncommitted (alarms 0025), and this finds it. Read-only, a scan at check time,
    never in a pass. Run with `manage.py check --database default` (after migrate, after a restore); quiet until the
    queue's `migration` has run."""
    from django.db import DatabaseError, connection
    from django.db.migrations.recorder import MigrationRecorder
    try:
        if ('alarms', migration) not in MigrationRecorder(connection).applied_migrations():
            return []
        with connection.cursor() as cursor:
            found = scan(cursor)
    except DatabaseError:
        return []
    return [Warning(f'{len(ids)} {said}: {_ids(ids)}.', hint=f"As the database's owner role: {repair}", id=check)
            for ids, (said, repair) in zip(found, (missing, stale)) if ids]


def _ids(ids):
    return ', '.join(str(each) for each in ids[:SHOWN]) + (f' and {len(ids) - SHOWN} more' if len(ids) > SHOWN else '')
