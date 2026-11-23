"""How the alarms are sealed (core.sealing): an alarm at a sealed cell's sampling point, opened inside the cell, or the
mirror of a sensor alarm event on a sealed channel, does not exist for someone the cell's owner has not granted; its
clearance, notifications, their delivery attempts, escalations and acknowledgements go with it, and so does the subject
whose open alarm it is. An alarm of the alarm system itself (a device's clock) lies on no cell."""
from core.sealing import declare


def declare_all():
    from . import models as m
    declare(m.Alarm, part='water', unit='point__unit', system='point__system', day='opened_at',
            via=('sensor_event',))
    for model in (m.AlarmClearance, m.Escalation, m.Acknowledgement, m.Notification):
        declare(model, part='water', via=('alarm',))
    declare(m.DeliveryAttempt, part='water', via=('notification',))
    declare(m.AlarmSubjectState, part='water', via=('open_alarm',))
