from django import forms
from django.contrib.auth import forms as auth_forms, get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError

from . import access
from .crud import TabbedForm, tab_fields

User = get_user_model()


class PermissionMatrix(forms.CheckboxSelectMultiple):
    """A role's permissions as the access matrix (core.access): a row per area under its group, a
    column per action, a box only where the area offers the action. Create, Edit and Delete point at
    their row's Read box (data-requires, see frontend/components.ts)."""

    template_name = 'core/widgets/permission_matrix.html'

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        options = {access.perm_name(option['value'].instance): option
                   for _, group, _ in context['widget']['optgroups'] for option in group}
        sections = {}
        for area in access.areas():
            cells = {action: options.get(area.perm(action)) for action in area.actions}
            read = cells.get(access.READ)
            for action, cell in cells.items():
                if cell and read and action != access.READ:
                    cell['attrs']['data-requires'] = read['attrs']['id']
            sections.setdefault(area.group, []).append(
                {'label': area.label, 'cells': [(label, cells.get(action)) for action, label in access.ACTIONS]})
        context['widget']['columns'] = [label for _, label in access.ACTIONS]
        context['widget']['sections'] = sections.items()
        return context


ROLE_FORM_TABS = [('role', 'Role', ['name', 'permissions'])]


class RoleForm(TabbedForm):
    tabs = ROLE_FORM_TABS

    class Meta:
        model = Group
        fields = tab_fields(ROLE_FORM_TABS)
        labels = {'name': 'Role name', 'permissions': 'Permissions'}
        help_texts = {'permissions': 'Create, Edit and Delete include Read. '
                                     'Roles and users are managed by the platform admin only.'}
        error_messages = {'name': {'unique': 'Another role already uses this name.'}}
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'e.g. Site manager'}),
            'permissions': PermissionMatrix,
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Only what the matrix offers: saving the role sets exactly the ticked boxes.
        self.fields['permissions'].queryset = access.permissions()

    def clean_name(self):
        return self.cleaned_data['name'].strip()

    def clean_permissions(self):
        names = access.implied(access.perm_name(permission) for permission in self.cleaned_data['permissions'])
        return [permission for permission in self.fields['permissions'].queryset
                if access.perm_name(permission) in names]


USER_FORM_TABS = [('account', 'Account', ['username', 'first_name', 'last_name', 'email', 'is_active', 'groups'])]


class UserForm(TabbedForm):
    """A person's account. Who may sign in is `is_active`: people are deactivated, not deleted, so
    their name stays on their history. Platform admin status is not set here."""

    tabs = USER_FORM_TABS

    class Meta:
        model = User
        fields = tab_fields(USER_FORM_TABS)
        labels = {'email': 'Email', 'is_active': 'Active', 'groups': 'Roles'}
        help_texts = {
            'username': 'Used to sign in. Letters, digits and @ . + - _ only.',
            'email': 'The invitation to set a password is sent here.',
            'is_active': 'Inactive people cannot sign in.',
            'groups': 'What the person can open and change. Without a role they see only the overview.',
        }
        widgets = {
            'username': forms.TextInput(attrs={'placeholder': 'e.g. kari.nordmann'}),
            'email': forms.EmailInput(attrs={'placeholder': 'email@example.com'}),
            'groups': forms.CheckboxSelectMultiple(attrs={'class': 'choices'}),
        }

    def __init__(self, *args, editor, **kwargs):
        super().__init__(*args, **kwargs)
        self.editor = editor
        self.fields['email'].required = True
        self.fields['groups'].queryset = Group.objects.order_by('name')
        if self.instance._state.adding:
            # A new person has no password until they set one through the invitation link.
            self.instance.set_unusable_password()

    def clean_email(self):
        email = self.cleaned_data['email']
        if User.objects.exclude(pk=self.instance.pk).filter(email__iexact=email).exists():
            raise ValidationError('Another user already uses this email.')
        return email

    def clean_is_active(self):
        active = self.cleaned_data['is_active']
        if not active and self.instance.pk == self.editor.pk:
            raise ValidationError('You cannot deactivate your own account.')
        return active


class PasswordResetForm(auth_forms.PasswordResetForm):
    """Django's reset form, also for people who have not set a password yet: users the platform admin
    creates start without one, and this email is their invitation (and its replacement once the
    link has expired)."""

    def get_users(self, email):
        users = User._default_manager.filter(email__iexact=email, is_active=True)
        return (user for user in users if auth_forms._unicode_ci_compare(email, user.email))
