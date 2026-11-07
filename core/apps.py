from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = 'core'

    def ready(self):
        from . import checks, dates  # noqa: F401  checks registers the system checks
        # Every form's date and moment, a model form's too: the shared box typed dd.mm.yyyy [HH:MM] (owner rule), never the
        # browser's own; the shape said in an error, one window of dates, a moment's time required (core/dates.py).
        dates.install()
