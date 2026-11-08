from django.apps import AppConfig
from django.core.signals import request_finished


class CoreConfig(AppConfig):
    name = 'core'

    def ready(self):
        from django.conf import settings

        from . import checks, dates  # noqa: F401  checks registers the system checks
        from .language import end_request_language
        request_finished.connect(end_request_language, dispatch_uid='core.language.end_request_language')
        # Every form's date and moment, a model form's too: the shared box typed dd.mm.yyyy [HH:MM] (owner rule), never the
        # browser's own; the shape said in an error, one window of dates, a moment's time required (core/dates.py).
        dates.install()
        if settings.CLOCK_GUARD:            # the tests: |date and |time refuse an aware moment without a clock filter
            from . import clock_guard
            clock_guard.install()
