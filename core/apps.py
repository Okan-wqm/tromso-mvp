from django.apps import AppConfig
from django.core.signals import request_finished


class CoreConfig(AppConfig):
    name = 'core'

    def ready(self):
        from . import checks  # noqa: F401  registers the system checks
        from .language import end_request_language
        request_finished.connect(end_request_language, dispatch_uid='core.language.end_request_language')
