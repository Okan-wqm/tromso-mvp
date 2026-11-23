"""What the data map (core.datamap) cannot read from the code, for the alarms' tables."""
from core.datamap import Screen, no, system

from .views import alarm_acknowledge, alarm_detail, alarm_list, alarm_snooze, alarm_snooze_end, alarm_snoozes

LOOP = 'written by the alarm pass (alarms/engine.py: the worker, manage.py run_alarm_worker, or run_alarms once)'
APPEND_ONLY = 'append-only: a database trigger refuses UPDATE and DELETE, even for the platform admin'

SCREENS = {
    'AlarmSubjectState': Screen(
        create=no(LOOP), edit=no("only the loop moves a subject's timers and its open alarm"),
        delete=no("a subject's row is kept: its timers survive a restart"),
        read=no("the loop's own memory; the alarms it opened are on the Alarms page"),
        columns={'*': system('the timers and the open alarm the loop keeps per subject (alarms/sources.py advance)')}),
    'AlarmWorkerStatus': Screen(
        create=no('the alarm worker writes its own row when it takes the lock (alarms/worker.py)'),
        edit=no('only the worker moves its row: each pass, each look, and when it stops'),
        delete=no("the worker's row is kept: the time of its last pass is what says the alarms went unchecked"),
        read=no('manage.py alarm_worker_health reads it (alarms/watch.py)'),
        columns={'*': system('the alarm worker, on the database clock')}),
    'SeverityPolicy': Screen(create=no('migration 0002 makes one row per severity'),
                             delete=no('there is always one row per severity')),
    'Alarm': Screen(create=no(LOOP), edit=no(APPEND_ONLY), delete=no(APPEND_ONLY), read=(alarm_list, alarm_detail),
                    columns={'*': system(LOOP)}),
    'AlarmClearance': Screen(create=no(LOOP), edit=no(APPEND_ONLY), delete=no(APPEND_ONLY),
                             read=(alarm_list, alarm_detail), columns={'*': system(LOOP)}),
    'Notification': Screen(create=no(LOOP), edit=no(APPEND_ONLY), delete=no(APPEND_ONLY), read=(alarm_detail,),
                           columns={'*': system(LOOP)}),
    'DeliveryAttempt': Screen(create=no('written by run_alarms when a transport took or refused a notification'),
                              edit=no(APPEND_ONLY), delete=no(APPEND_ONLY), read=(alarm_detail,),
                              columns={'*': system('written by run_alarms from what the transport answered')}),
    'Escalation': Screen(create=no(LOOP), edit=no(APPEND_ONLY), delete=no(APPEND_ONLY), read=(alarm_list, alarm_detail),
                         columns={'*': system(LOOP)}),
    'AlarmShelve': Screen(create=(alarm_snooze,), edit=no(APPEND_ONLY), delete=no(APPEND_ONLY),
                          read=(alarm_snoozes, alarm_detail),
                          columns={'*': system('the person, the moment, until when and why, as they snoozed it')}),
    'AlarmShelveEnd': Screen(create=(alarm_snooze_end,), edit=no(APPEND_ONLY), delete=no(APPEND_ONLY),
                             read=(alarm_snoozes, alarm_detail),
                             columns={'*': system('the person and the moment they ended a snooze early')}),
    'Acknowledgement': Screen(create=(alarm_acknowledge, 'sensors:alarm_event_acknowledge'), edit=no(APPEND_ONLY),
                              delete=no(APPEND_ONLY), read=(alarm_list, alarm_detail),
                              columns={'*': system('the person, the moment and the app or device that said it')},
                              note='The mobile app will acknowledge through the same service (alarms.services.acknowledge).'),
}
