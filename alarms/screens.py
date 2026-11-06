"""What the data map (core.datamap) cannot read from the code, for the alarms' tables."""
from core.datamap import Screen, no, system

from .views import alarm_acknowledge, alarm_detail, alarm_list

LOOP = 'written by manage.py run_alarms (alarms/engine.py)'
APPEND_ONLY = 'append-only: a database trigger refuses UPDATE and DELETE, even for the platform admin'

SCREENS = {
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
    'Acknowledgement': Screen(create=(alarm_acknowledge, 'sensors:alarm_event_acknowledge'), edit=no(APPEND_ONLY),
                              delete=no(APPEND_ONLY), read=(alarm_list, alarm_detail),
                              columns={'*': system('the person, the moment and the app or device that said it')},
                              note='The mobile app will acknowledge through the same service (alarms.services.acknowledge).'),
}
