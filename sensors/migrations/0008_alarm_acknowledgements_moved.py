from django.db import migrations


def carry_over(apps, schema_editor):
    """Every event becomes an alarm of the alarms app (with its clearance when it closed), and every acknowledgement kept
    on an event becomes an Acknowledgement of that alarm (app 'console', no device: the Alarm events page was the only way
    to acknowledge). Events mirrored already keep their alarm; nothing is written twice."""
    AlarmEvent = apps.get_model('sensors', 'AlarmEvent')
    Channel = apps.get_model('sensors', 'Channel')
    Alarm = apps.get_model('alarms', 'Alarm')
    Clearance = apps.get_model('alarms', 'AlarmClearance')
    Acknowledgement = apps.get_model('alarms', 'Acknowledgement')
    channels = {channel.channel_no: channel for channel in Channel._base_manager.select_related('device')}
    for event in AlarmEvent.objects.select_related('rule').order_by('opened_at', 'pk'):
        alarm = Alarm.objects.filter(sensor_event=event).first()
        if alarm is None:
            channel = channels.get(event.channel_no)
            scope = channel.code if channel is not None else event.rule.quantity
            where = f' · {channel.device.code}' if channel is not None else f' #{event.channel_no}'
            alarm = Alarm.objects.create(source='sensor_rule', sensor_event=event, severity=event.rule.severity,
                                         site_id=channel.device.site_id if channel is not None else None,
                                         opened_at=event.opened_at, summary=f'{scope}: {event.rule.kind}{where}'[:300])
            if event.closed_at is not None:
                Clearance.objects.create(alarm=alarm, cleared_at=event.closed_at)
        if event.acknowledged_at is not None and not Acknowledgement.objects.filter(alarm=alarm).exists():
            Acknowledgement.objects.create(alarm=alarm, user_id=event.acknowledged_by_id, app='console', device='',
                                           acknowledged_at=event.acknowledged_at)


def carry_back(apps, schema_editor):
    """Going back: each event gets the first acknowledgement of its alarm again (the alarms' rows stay: they are
    append-only)."""
    AlarmEvent = apps.get_model('sensors', 'AlarmEvent')
    Acknowledgement = apps.get_model('alarms', 'Acknowledgement')
    for ack in Acknowledgement.objects.filter(alarm__sensor_event__isnull=False).select_related('alarm').order_by(
            'acknowledged_at', 'pk'):
        AlarmEvent.objects.filter(pk=ack.alarm.sensor_event_id, acknowledged_at__isnull=True).update(
            acknowledged_by_id=ack.user_id, acknowledged_at=ack.acknowledged_at)


class Migration(migrations.Migration):
    """Who acknowledged a sensor alarm event moves to the alarms app: one record of every acknowledgement, append-only."""

    dependencies = [
        ('sensors', '0007_device_site'),
        ('alarms', '0001_initial'),
    ]

    # The columns go in the next migration, in a transaction of their own (no ALTER TABLE after these inserts).
    operations = [migrations.RunPython(carry_over, carry_back)]
