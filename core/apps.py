from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = 'core'

    def ready(self):
        from django import forms

        from . import checks  # noqa: F401  registers the system checks
        from .widgets import DayInput, MomentInput
        # Every form's date and moment, a model form's too, is the shared box typed dd.mm.yyyy [HH:MM] (owner rule), never
        # the browser's own (core/tests_date_inputs.py); a field may still name another widget.
        forms.DateField.widget = DayInput
        forms.DateTimeField.widget = MomentInput
