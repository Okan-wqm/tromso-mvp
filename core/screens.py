"""What the data map (core.datamap) cannot read from the code, for the core tables."""
from .datamap import Screen, no, system
from .forms import UserForm
from .resources import UserResource
from .views import activity_log, set_language

SCREENS = {
    'AuditLog': Screen(
        create=no('written by the code: every create, change, delete, restore and void of every record logs itself '
                  '(core.audit)'),
        edit=no('append-only: a database trigger refuses UPDATE and DELETE, even for the platform admin'),
        delete=no('append-only: a database trigger refuses UPDATE and DELETE, even for the platform admin'),
        read=(activity_log,),
        note="A record's own rows are also shown on the History tab of its edit page.",
        columns={'*': system('written by core.audit when the change is saved')},
    ),
    'Profile': Screen(
        create=(set_language, UserResource),
        edit=(set_language, UserResource),
        delete=no('a profile goes with its person, and people are deactivated, never deleted'),
        read=(UserResource,),
        note='Today the profile holds the language only: chosen with the language switcher, or on the Users tab.',
        forms=(UserForm,),
        columns={'user': system('the person the profile belongs to')},
    ),
}
