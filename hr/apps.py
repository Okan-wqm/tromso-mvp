from django.apps import AppConfig


class HrConfig(AppConfig):
    name = 'hr'

    def ready(self):
        from . import resources  # noqa: F401  declares the tabs on Resource.registry
        from core import audit
        from .models import Employee, Posting, ShiftAssignment
        # What the activity log says about the people (who they are, where they are placed) is for the holders of
        # Everyone only; a record's own history stays on its page, which the team scope already guards.
        for model in (Employee, Posting, ShiftAssignment):
            audit.restrict(audit.entity_type_of(model), 'hr.all_employee')
