"""How the alarms are sealed (core.sealing): an alarm at a sealed cell's sampling point, opened inside the cell, or the
mirror of a sensor alarm event on a sealed channel, does not exist for someone the cell's owner has not granted; its
clearance, notifications, their delivery attempts and outbox entries, escalations, acknowledgements and snoozes
(and their ends) go with it, and so does the subject whose open alarm it is. An alarm of the alarm system itself (a device's clock) lies on no cell."""
from core.sealing import declare


def declare_all():
    from . import models as m
    # Its place is kept on it when it opens (alarms/place.py: a unit subject's, a point's, a sensor channel's then), and
    # a row written without one is still sealed by its point (fail closed).
    declare(m.Alarm, part='water', unit=('unit', 'point__unit'), system=('system', 'point__system'), day='opened_at',
            via=('sensor_event',))
    for model in (m.AlarmClearance, m.Escalation, m.Acknowledgement, m.Notification, m.AlarmShelve):
        declare(model, part='water', via=('alarm',))
    for model in (m.DeliveryAttempt, m.OutboxEntry):
        declare(model, part='water', via=('notification',))
    declare(m.AlarmShelveEnd, part='water', via=('shelve',))
    declare(m.AlarmSubjectState, part='water', via=('open_alarm',))
