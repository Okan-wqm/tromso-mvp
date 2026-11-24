"""Which alarms of the alarm system are about its OWN health (the coordinator's call on the follow-up review, R6): the
alarms not checked for a while (the worker was down), a step of the pass failing (the outbox's sender among them),
critical notifications that cannot be delivered, the alarm rules incomplete. These are never snoozed: they say the
alarms themselves are not working, and the sensors that cannot be read (the farm is blind). Every other alarm the alarm
system raises is about one place of the farm (a unit cannot be evaluated, a value without a number, a device clock, an
oxygen with no fresh value) and is snoozed like any alarm, with a reason and within its severity's longest snooze. A kind joins here by name; nothing else
decides it."""
OWN_HEALTH = frozenset({'alarms_unchecked', 'step_failed', 'notifications_undeliverable', 'alarm_rules',
                        # the live values cannot be read: the farm is blind (the coordinator's call on the recheck)
                        'sensors_failed'})
