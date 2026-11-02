"""Roles and users, declared on top of core.crud. Their permissions (auth.*_group, auth.*_user) are
not in the access matrix, so only the platform admin manages them."""
from django.contrib.auth.models import Group

from . import access, audit
from .crud import Resource
from .forms import PasswordResetForm, RoleForm, User, UserForm


class RoleResource(Resource):
    model = Group
    form_class = RoleForm
    name, plural, group = 'role', 'roles', 'Administration'
    url_prefix = 'roles'
    namespace = 'core'
    search_fields = ['name']
    list_template = 'core/role_list.html'
    icon = 'shield'

    @classmethod
    def queryset(cls):
        return Group.objects.order_by('name').prefetch_related('permissions__content_type', 'user_set')

    @classmethod
    def snapshot(cls, role):
        """The name, and the permissions as the matrix reads them ('Sites: read, create; ...')."""
        values = audit.snapshot(role, ['name'], RoleForm.Meta.labels)
        values['Permissions'] = access.summary(role.permissions.select_related('content_type')) or None
        return values


class UserResource(Resource):
    model = User
    form_class = UserForm
    name, plural, group = 'user', 'users', 'Administration'
    url_prefix = 'users'
    namespace = 'core'
    actions = ('add', 'change')     # people are deactivated, not deleted
    search_fields = ['username', 'first_name', 'last_name', 'email']
    list_template = 'core/user_list.html'
    icon = 'users'

    @classmethod
    def queryset(cls):
        return User.objects.order_by('username').prefetch_related('groups')

    @classmethod
    def form(cls, request, *args, **kwargs):
        return cls.form_class(*args, editor=request.user, **kwargs)

    @classmethod
    def after_save(cls, request, user, created):
        """A new person is invited with the password reset email: its link sets their first password."""
        if created:
            invitation = PasswordResetForm({'email': user.email})
            invitation.is_valid()
            invitation.save(request=request, use_https=request.is_secure())
