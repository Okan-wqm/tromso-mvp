"""What the data map (core.datamap) cannot read from the code, for the core tables."""
from .datamap import Screen, gap, no, system
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
    'Rev': Screen(
        create=no('written by the database: a trigger of each tracked table moves its revision at commit (core.rev)'),
        edit=no('written by the database; `manage.py core_rev_rebuild` moves every revision after a restore'),
        delete=no('derived data, safe to rebuild: a revision is never deleted'),
        read=no('read by the code that proves a stored figure still valid; the database viewer shows the table'),
        columns={'*': system('moved by the revision triggers (core.operations.TrackRev)')},
    ),
    'Job': Screen(
        create=no('queued by the code that asks for background work, in its own transaction (core.jobs)'),
        edit=no('moved by the worker (manage.py run_worker): claimed, done, tried again, dead'),
        delete=no('kept as the record of what ran; a pruning job is a later step'),
        read=gap('the Background jobs page (Administration, view only for the administrator) comes with the menu and '
                 'role-matrix wiring; until then /healthz shows the dead and waiting counts'),
        columns={'*': system('written by core.jobs and the worker')},
    ),
    'WorkerBeat': Screen(
        create=no('written by the worker at every round (core.jobs.beat)'),
        edit=no('written by the worker at every round (core.jobs.beat)'),
        delete=no('one row per worker name, kept'),
        read=gap('shown on /healthz as the age of the last beat; the Background jobs page will show it'),
        columns={'*': system('written by the worker')},
    ),
}
