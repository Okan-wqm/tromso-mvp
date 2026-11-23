"""How the sensors are sealed (core.sealing): a binding on a sealed cell's sampling point or system, over days inside
the cell, does not exist for someone not granted; a channel that ever had such a binding is absent for them (the
conservative first rule: its readings are one series), and so are its calibrations, alarm rules and their events. The
readings themselves are never filtered: a reading is reached only through a channel these managers return
(sensors/read.py). A device is plant, like a piece of equipment."""
from core.sealing import EXEMPT, declare


def declare_all():
    from . import models as m
    declare(m.Binding, part='water', unit='point__unit', system=('system', 'point__system'),
            day=('valid_from', 'valid_to'))
    declare(m.Channel, part='water', hidden_with=('sensors.Binding', 'channel'))
    declare(m.Calibration, part='water', via=('channel',))
    declare(m.AlarmRule, part='water', via=('channel',))
    declare(m.AlarmEvent, part='water', via=('rule',))
    declare(m.Device, mode=EXEMPT, reason='A device is plant on a site (a probe, a controller); what it measures where '
                                          'is its channels\' bindings, which are sealed.')
