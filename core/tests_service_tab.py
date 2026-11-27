"""A tab whose service writes its records (core.crud.Resource.service_writes) hands crud nothing to save beside the
record: crud skips `form.save_m2m()`, `change_severity` and `after_save` for it, and a row list is saved by crud itself.
A tab that sets the flag and has one of them would lose it without a word, so the combination is refused when the class
is defined (the review of wip/hr-one-path, L-5)."""
from django import forms
from django.contrib.auth.models import Group
from django.test import SimpleTestCase

from .crud import Resource, RowList
from .models import AuditLog


class GroupForm(forms.ModelForm):
    class Meta:
        model = Group
        fields = ['name', 'permissions']          # a many-to-many field on the form


class EverythingForm(forms.ModelForm):
    class Meta:
        model = Group
        fields = '__all__'                       # the many-to-many field too, by '__all__'


class NameForm(forms.ModelForm):
    class Meta:
        model = Group
        fields = ['name']


class ServiceTabTests(SimpleTestCase):
    def define(self, **attributes):
        """Declares a tab and takes it off the registry again, whatever happened."""
        declared = list(Resource.registry)
        try:
            return type('ProbeResource', (Resource,), {'model': Group, 'form_class': NameForm, **attributes})
        finally:
            Resource.registry[:] = declared

    def test_a_service_tab_with_nothing_beside_the_record_is_declared(self):
        self.assertTrue(self.define(service_writes=True).service_writes)
        self.define(form_class=GroupForm, row_lists=(RowList,))        # crud saves these itself: no flag, no refusal

    def test_a_service_tab_with_what_crud_would_drop_is_refused_when_declared(self):
        for name, attributes in (
                ('a many-to-many field', {'form_class': GroupForm}),
                ('a many-to-many field by __all__', {'form_class': EverythingForm}),
                ('a row list', {'row_lists': (RowList,)}),
                ('a change severity', {'change_severity': classmethod(lambda cls, before, obj: AuditLog.Severity.CRITICAL)}),
                ('an after_save', {'after_save': classmethod(lambda cls, request, obj, created: None)})):
            with self.subTest(what=name), self.assertRaises(TypeError):
                self.define(service_writes=True, **attributes)
