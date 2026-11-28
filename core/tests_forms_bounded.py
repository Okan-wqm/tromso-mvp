"""Review 5, R5-6: every model form's number inputs take their bounds from the model (core.crud.BoundedModelForm,
`bounded_inputs`), applied once by the base every model form of the project derives from; no form sets them by hand."""
from django import forms
from django.test import SimpleTestCase

from .modules import is_test_module

PROJECT_APPS = ('alarms', 'core', 'experiments', 'farm', 'hr', 'inventory', 'knowledge', 'messaging', 'monitoring',
                'reports', 'sensors', 'tasks')


def bounds(form, name):
    attrs = form.fields[name].widget.attrs
    return (attrs.get('min'), attrs.get('max'))


class BoundedFormsTests(SimpleTestCase):
    def test_every_model_form_of_the_project_derives_from_the_bounded_base(self):
        from core.crud import BoundedModelForm
        from core.datamap import all_model_forms
        found = sorted(f'{form.__module__}.{form.__qualname__}' for form in all_model_forms()
                       if form.__module__.split('.')[0] in PROJECT_APPS
                       and not is_test_module(form.__module__.replace('.', '/') + '.py')
                       and issubclass(form, forms.ModelForm) and not issubclass(form, BoundedModelForm))
        self.assertEqual(found, [], 'A model form of the project derives from core.crud.BoundedModelForm (or TabbedForm).')

    def test_the_inputs_say_the_models_bounds(self):
        from farm.forms.health import MedicineWithdrawalForm
        from farm.models.health import MAX_WITHDRAWAL_DAYS
        from farm.forms.site import SiteForm
        from monitoring.forms import MonitorBoardForm
        withdrawal = MedicineWithdrawalForm()
        self.assertEqual(bounds(withdrawal, 'days'), (0, MAX_WITHDRAWAL_DAYS))
        self.assertEqual(bounds(withdrawal, 'degree_days'), (None, None))      # a localised decimal typed as text
        board = MonitorBoardForm()
        self.assertEqual(bounds(board, 'refresh_seconds'), (10, 600))
        self.assertEqual(bounds(board, 'screen_inches'), ('10', '150'))         # a decimal's bounds as text
        self.assertEqual(bounds(board, 'distance_m'), ('0.5', '20'))
        self.assertEqual(board.fields['distance_m'].widget.attrs.get('step'), '0.1')
        self.assertEqual(bounds(SiteForm(), 'lokalitetsnummer'), (10000, 99999))
