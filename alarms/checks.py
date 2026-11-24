"""The alarms' deployment check (`manage.py check --deploy`, and so CI and a release): every transport named in
settings.ALARM_TRANSPORTS imports, is a Transport, and declares `max_bytes`, a whole number of at least 1 (REVIEW4: a
transport without a limit sends nothing, and that would only show at the first real alarm, perhaps at night).

A deployment check only, never an ordinary one: Django runs the ordinary checks before every management command, so one
wrong transport setting at Error level would stop `manage.py run_alarm_worker`, and no alarm would be checked at all."""
from django.conf import settings
from django.core.checks import Error, register
from django.utils.module_loading import import_string

from .transports import Transport


@register(deploy=True)
def transports_declare_limits(app_configs, **kwargs):
    errors = []
    for channel, path in sorted(getattr(settings, 'ALARM_TRANSPORTS', {}).items()):
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
