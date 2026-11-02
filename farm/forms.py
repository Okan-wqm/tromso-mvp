from django import forms
from django.core.exceptions import ValidationError

from core.crud import TabbedForm, tab_fields

from .models import Site, SiteContact

# The source form's inner tabs (Basic info / Location info / Contact info) and their fields.
SITE_FORM_TABS = [
    ('basic', 'Basic info', [
        'name', 'code', 'lokalitetsnummer', 'organisation_number_override', 'description',
        'type', 'status', 'area_m2', 'timezone',
    ]),
    ('location', 'Location', [
        'country', 'region', 'street', 'city', 'state', 'postal_code', 'latitude', 'longitude', 'altitude',
    ]),
    ('contact', 'Contact', ['site_manager', 'contact_email', 'contact_phone']),
]


class SiteForm(TabbedForm):
    tabs = SITE_FORM_TABS

    class Meta:
        model = Site
        fields = tab_fields(SITE_FORM_TABS)
        labels = {
            'name': 'Site name',
            'code': 'Site code',
            'lokalitetsnummer': 'Lokalitetsnummer',
            'organisation_number_override': 'Organisation number override',
            'type': 'Site type',
            'area_m2': 'Total area (m²)',
            'street': 'Street address',
            'postal_code': 'Postal code',
            'altitude': 'Altitude (m)',
            'site_manager': 'Site manager',
            'contact_email': 'Contact email',
            'contact_phone': 'Contact phone',
        }
        help_texts = {
            'lokalitetsnummer': 'Akvakulturregisteret locality number (5 digits). '
                                'Norwegian regulatory reports cannot be filed without it.',
            'timezone': 'Feeding jobs run on the site’s local day. Leave it inherited unless the site is '
                        'in a different timezone than the company.',
            'latitude': 'Required for a sea cage.',
        }
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'e.g. Main Production Site'}),
            'code': forms.TextInput(attrs={'placeholder': 'e.g. MPS-001', 'data-uppercase': ''}),
            'lokalitetsnummer': forms.NumberInput(attrs={'placeholder': 'e.g. 12345', 'min': 10000, 'max': 99999}),
            'organisation_number_override': forms.TextInput(attrs={'placeholder': '9-digit Norwegian organisation number'}),
            'description': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Brief description of the site'}),
            'area_m2': forms.NumberInput(attrs={'placeholder': 'e.g. 50000', 'step': 'any'}),
            'country': forms.TextInput(attrs={'placeholder': 'e.g. Norway'}),
            'region': forms.TextInput(attrs={'placeholder': 'e.g. Vestland'}),
            'latitude': forms.NumberInput(attrs={'placeholder': 'e.g. 60.3913', 'step': 'any'}),
            'longitude': forms.NumberInput(attrs={'placeholder': 'e.g. 5.3221', 'step': 'any'}),
            'altitude': forms.NumberInput(attrs={'placeholder': 'Optional', 'step': 'any'}),
            'site_manager': forms.TextInput(attrs={'placeholder': 'Full name of the site manager'}),
            'contact_email': forms.EmailInput(attrs={'placeholder': 'email@example.com'}),
            'contact_phone': forms.TextInput(attrs={'placeholder': '+47 XXX XX XXX', 'type': 'tel'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['timezone'].choices = [('', 'Inherit from company')] + Site.TIMEZONES

    def clean_code(self):
        code = self.cleaned_data['code'].strip().upper()
        if len(code) < 2:
            raise ValidationError('Code must be at least 2 characters.')
        return code

    def clean_name(self):
        return self.cleaned_data['name'].strip()

    def clean(self):
        cleaned = super().clean()
        latitude, longitude = cleaned.get('latitude'), cleaned.get('longitude')
        if cleaned.get('type') == Site.Type.SEA_CAGE:
            if latitude is None and 'latitude' not in self.errors:
                self.add_error('latitude', 'Latitude is required for a sea cage.')
            if longitude is None and 'longitude' not in self.errors:
                self.add_error('longitude', 'Longitude is required for a sea cage.')
        elif (latitude is None) != (longitude is None):
            field = 'longitude' if longitude is None else 'latitude'
            self.add_error(field, 'Latitude and longitude must be provided together.')

        # Unique among live sites. The database constraints enforce the same, but Django skips them
        # during form validation because their condition uses is_deleted, which is not a form field.
        others = Site.objects.exclude(pk=self.instance.pk)
        for field, lookup in (('code', 'code'), ('name', 'name'), ('lokalitetsnummer', 'lokalitetsnummer')):
            value = cleaned.get(field)
            if value not in (None, '') and field not in self.errors and others.filter(**{lookup: value}).exists():
                self.add_error(field, f'Another site already uses this {self.fields[field].label.lower()}.')
        return cleaned


class SiteContactForm(forms.ModelForm):
    class Meta:
        model = SiteContact
        fields = ['name', 'role', 'email', 'phone', 'is_primary']
        labels = {'is_primary': 'Primary'}
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'Name'}),
            'role': forms.TextInput(attrs={'placeholder': 'Role'}),
            'email': forms.EmailInput(attrs={'placeholder': 'Email'}),
            'phone': forms.TextInput(attrs={'placeholder': 'Phone', 'type': 'tel'}),
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
            raise ValidationError(f'Only one contact can be the primary contact; {primaries} are marked.')

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
