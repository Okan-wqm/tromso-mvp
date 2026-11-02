from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from core.crud import CodedFormMixin, TabbedForm, tab_fields

from ..models import Site, SiteContact

# The source form's inner tabs (Basic info / Location info / Contact info) and their fields.
SITE_FORM_TABS = [
    ('basic', _('Basic info'), [
        'name', 'code', 'lokalitetsnummer', 'organisation_number_override', 'description',
        'type', 'status', 'area_m2', 'timezone',
    ]),
    ('location', _('Location'), [
        'country', 'region', 'street', 'city', 'state', 'postal_code', 'latitude', 'longitude', 'altitude',
    ]),
    ('contact', _('Contact'), ['site_manager', 'contact_email', 'contact_phone']),
]


class SiteForm(CodedFormMixin, TabbedForm):
    tabs = SITE_FORM_TABS

    class Meta:
        model = Site
        fields = tab_fields(SITE_FORM_TABS)
        # Quantities are typed and shown the way the language writes them (50000,5 or 50000.5), so
        # they are text inputs: a number input would use the browser's own language instead.
        localized_fields = ['area_m2', 'latitude', 'longitude', 'altitude']
        help_texts = {
            'lokalitetsnummer': _('Akvakulturregisteret locality number (5 digits). '
                                  'Norwegian regulatory reports cannot be filed without it.'),
            'timezone': _('Feeding jobs run on the site’s local day. Leave it inherited unless the site is '
                          'in a different timezone than the company.'),
            'latitude': _('Required for a sea cage.'),
        }
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': _('e.g. Main Production Site')}),
            'code': forms.TextInput(attrs={'placeholder': _('e.g. MPS-001'), 'data-uppercase': ''}),
            'lokalitetsnummer': forms.NumberInput(attrs={'placeholder': _('e.g. 12345'), 'min': 10000, 'max': 99999}),
            'organisation_number_override': forms.TextInput(
                attrs={'placeholder': _('9-digit Norwegian organisation number')}),
            'description': forms.Textarea(attrs={'rows': 3, 'placeholder': _('Brief description of the site')}),
            'area_m2': forms.TextInput(attrs={'placeholder': _('e.g. 50000'), 'inputmode': 'decimal'}),
            'country': forms.TextInput(attrs={'placeholder': _('e.g. Norway')}),
            'region': forms.TextInput(attrs={'placeholder': _('e.g. Vestland')}),
            'latitude': forms.TextInput(attrs={'placeholder': _('e.g. 60.3913'), 'inputmode': 'decimal'}),
            'longitude': forms.TextInput(attrs={'placeholder': _('e.g. 5.3221'), 'inputmode': 'decimal'}),
            'altitude': forms.TextInput(attrs={'placeholder': _('Optional'), 'inputmode': 'decimal'}),
            'site_manager': forms.TextInput(attrs={'placeholder': _('Full name of the site manager')}),
            'contact_email': forms.EmailInput(attrs={'placeholder': 'email@example.com'}),
            'contact_phone': forms.TextInput(attrs={'placeholder': '+47 XXX XX XXX', 'type': 'tel'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['timezone'].choices = [('', _('Inherit from company'))] + Site.TIMEZONES

    def clean(self):
        cleaned = super().clean()
        latitude, longitude = cleaned.get('latitude'), cleaned.get('longitude')
        if cleaned.get('type') == Site.Type.SEA_CAGE:
            if latitude is None and 'latitude' not in self.errors:
                self.add_error('latitude', _('Latitude is required for a sea cage.'))
            if longitude is None and 'longitude' not in self.errors:
                self.add_error('longitude', _('Longitude is required for a sea cage.'))
        elif (latitude is None) != (longitude is None):
            field = 'longitude' if longitude is None else 'latitude'
            self.add_error(field, _('Latitude and longitude must be provided together.'))
        return cleaned


class SiteContactForm(forms.ModelForm):
    class Meta:
        model = SiteContact
        fields = ['name', 'role', 'email', 'phone', 'is_primary']
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': _('Name')}),
            'role': forms.TextInput(attrs={'placeholder': _('Role')}),
            'email': forms.EmailInput(attrs={'placeholder': _('Email')}),
            'phone': forms.TextInput(attrs={'placeholder': _('Phone'), 'type': 'tel'}),
            'is_primary': forms.CheckboxInput(attrs={'data-primary': ''}),
        }

    def validate_constraints(self):
        # The one-primary rule spans the whole list, which is saved as a full replace; the formset
        # checks it and the database constraint backs it up. Checking each row against the stored
        # rows would reject moving the primary flag from one contact to another.
        pass


class BaseSiteContactFormSet(forms.BaseInlineFormSet):
    def clean(self):
        super().clean()
        primaries = sum(
            1 for form in self.forms
            if form.cleaned_data.get('is_primary') and not form.cleaned_data.get('DELETE')
        )
        if primaries > 1:
            raise ValidationError(_('Only one contact can be the primary contact; %(count)d are marked.'),
                                  params={'count': primaries})

    def kept_rows(self):
        """Cleaned data of the rows to keep: not marked for removal and not an untouched blank row."""
        return [
            form.cleaned_data for form in self.forms
            if form.cleaned_data and not form.cleaned_data.get('DELETE')
            and (form.instance.pk or form.has_changed())
        ]


SiteContactFormSet = forms.inlineformset_factory(
    Site, SiteContact, form=SiteContactForm, formset=BaseSiteContactFormSet, extra=0, can_delete=True,
)
