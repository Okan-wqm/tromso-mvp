"""Roles and users, declared on top of core.crud. Their permissions (auth.*_group, auth.*_user) are
not in the access matrix, so only the platform admin manages them."""
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.models import Group
from django.db import transaction
from django.db.models import Prefetch
from django.urls import path
from django.utils.translation import gettext_lazy as _

from . import access, accountmail, audit
from .crud import Resource, ResourceView, done, tab_fields
from .forms import PlatformSettingsForm, RoleForm, User, UserForm
from .language import account_language
from .models import AccountMail, AuditLog, PlatformSettings



class RoleResource(Resource):
    model = Group
    form_class = RoleForm
    name, plural = _('role'), _('roles')
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
        values[str(RoleForm.Meta.labels['permissions'])] = (
            access.summary(role.permissions.select_related('content_type')) or None)
        return values


class InviteView(ResourceView):
    """The users tab's "Send invitation" button: the invitation of a person who has not set a password, sent (again)
    by who may change users, the platform admin. POST only; the person's row is locked while it is sent, so two
    clicks send one after the other."""
    action = 'change'

    def post(self, request, pk):
        mail = None
        with transaction.atomic():
            user = self.locked_object(pk)
            refusal = accountmail.cannot_invite(user)
            if refusal:
                messages.error(request, refusal)
            else:
                mail = self.resource.invite(request, user)
        if mail is not None:
            self.resource.send_off(request, mail)
        return done(request, self.url('list'))


class UserResource(Resource):
    model = User
    form_class = UserForm
    name, plural = _('user'), _('users')
    url_prefix = 'users'
    namespace = 'core'
    actions = ('add', 'change')     # people are deactivated, not deleted
    search_fields = ['username', 'first_name', 'last_name', 'email']
    list_template = 'core/user_list.html'
    icon = 'users'

    @classmethod
    def queryset(cls):
        # each person's invitations, newest first, for their row (accountmail.standing)
        invitations = AccountMail.objects.filter(kind=accountmail.INVITATION).order_by('-created_at', '-id')
        # and when each last set a password through a link (the activity log's own row of it)
        return accountmail.with_password_set(User.objects.order_by('username')).prefetch_related(
            'groups', Prefetch('account_mails', queryset=invitations, to_attr='invitations'))

    @classmethod
    def routes(cls, mount=None):
        return super().routes(mount) + [
            path(f'{cls.url_prefix}/<int:pk>/invite/', InviteView.as_view(resource=cls), name='user_invite')]

    @classmethod
    def form(cls, request, *args, **kwargs):
        return cls.form_class(*args, editor=request.user, **kwargs)

    @classmethod
    def snapshot(cls, user):
        """The account fields, and the language the form keeps on the profile (by its native name)."""
        fields = [name for name in tab_fields(UserForm.tabs) if name != 'language']
        values = audit.snapshot(user, fields, UserForm.Meta.labels)
        values[str(UserForm.base_fields['language'].label)] = dict(settings.LANGUAGES).get(account_language(user))
        return values

    @classmethod
    def after_save(cls, request, user, created):
        """A new person is invited: the link in the mail sets their first password (core.accountmail). The invitation
        is written here, as waiting, with the user; it is handed over to be sent once both are committed
        (after_commit). One without an address is created all the same, and the admin is told what that means; an
        edit sends nothing (the row offers the invitation)."""
        if not created:
            return
        if accountmail.cannot_invite(user) is None:
            user.queued_invitation = cls.invite(request, user)
        elif not user.email:
            messages.warning(request, _(
                'No invitation was sent: %(name)s has no email address. They cannot sign in until an address is added '
                'and the invitation sent.') % {'name': user.get_username()})

    @classmethod
    def after_commit(cls, request, user, created):
        mail = getattr(user, 'queued_invitation', None)
        if mail is not None:
            cls.send_off(request, mail)

    @classmethod
    def invite(cls, request, user):
        """Inside the caller's transaction: writes `user`'s invitation as waiting (accountmail.queue) and the activity
        log's row of it: who invited whom, when, to which address; never the link. Returns the mail, for `send_off`
        once the transaction has committed. Should it then not go out, the platform adds its own row
        (accountmail._close)."""
        mail = accountmail.queue(user, accountmail.INVITATION, by=request.user)
        audit.record(request.user, AuditLog.Action.INVITE, user, {accountmail.SENT_TO_LABEL: [None, mail.address]},
                     entity_type=cls.entity_type())
        return mail

    @classmethod
    def send_off(cls, request, mail):
        """After the commit, outside any lock: hands the waiting invitation to the mail worker and tells the admin
        where its outcome shows. The answer does not wait for the mail server."""
        if accountmail.hand_over(mail):
            messages.success(request, _('The invitation to %(address)s is being sent: this person’s row says whether '
                                        'it went out.') % {'address': mail.address})
        else:
            messages.error(request, _('The invitation to %(address)s was not sent: %(reason)s')
                           % {'address': mail.address, 'reason': _(accountmail.BUSY)})


class PlatformSettingsResource(Resource):
    """The platform owner's settings, one row: changed, never added or deleted (Platform settings: Edit is the platform
    owner's right). Every change is logged with its old and new value."""

    model = PlatformSettings
    form_class = PlatformSettingsForm
    name, plural = _('platform settings'), _('platform settings')
    url_prefix = 'administration/platform-settings'
    namespace = 'core'
    actions = ('change',)
    list_template = 'core/platform_settings.html'
    icon = 'settings'

    @classmethod
    def list_queryset(cls, request):
        PlatformSettings.get()            # the row exists even if a restore left none
        return super().list_queryset(request)
