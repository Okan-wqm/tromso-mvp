"""The account e-mails: the invitation a new person gets and the password reset. One path for both.

Each carries Django's own one-time link (`default_token_generator`, opened by `PasswordResetConfirmView`): it works
until the password is set, the address changes or settings.PASSWORD_RESET_TIMEOUT has passed, whichever comes first.
The link starts with settings.PUBLIC_BASE_URL, never with the Host header of the request that caused the mail, and the
mail is written in the recipient's saved language (otherwise in the language of whoever caused it). It goes out through
the default mailer (settings.MAILERS).

Every mail is recorded (`AccountMail`: who, which kind, to which address, by whom, and why not when it did not go out;
never the link). A mail that cannot be sent is not an error of the page that caused it: the record a person just
created stays, and the row says what happened."""
import logging
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ImproperlyConfigured
from django.core.mail import DEFAULT_MAILER_ALIAS, EmailMessage
from django.db import transaction
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone, translation
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.utils.translation import gettext as _

from .language import account_language
from .models import AccountMail
from .people import person_name

logger = logging.getLogger(__name__)

INVITATION, RESET = AccountMail.Kind.INVITATION, AccountMail.Kind.RESET
REASON_LENGTH = AccountMail._meta.get_field('error').max_length


def public_url(path):
    """`path` of this server as people reach it from outside."""
    if not settings.PUBLIC_BASE_URL:
        raise ImproperlyConfigured('PUBLIC_BASE_URL is not set: the link in the mail would lead nowhere.')
    return settings.PUBLIC_BASE_URL + path


def link_parts(user):
    """What Django's one-time link for `user` is made of: the person's id as the link carries it, and the token."""
    return urlsafe_base64_encode(force_bytes(user.pk)), default_token_generator.make_token(user)


def message(user, kind, by, language, uid, token):
    """The mail of `kind` (INVITATION or RESET) for `user` in `language`; `by` is who invited them."""
    context = {
        'name': person_name(user), 'username': user.get_username(),
        'link': public_url(reverse('password_reset_confirm', kwargs={'uidb64': uid, 'token': token})),
        'reset_url': public_url(reverse('password_reset')), 'hours': settings.PASSWORD_RESET_TIMEOUT // 3600,
        'company': settings.COMPANY_NAME, 'inviter': person_name(by) if by else '',
    }
    with translation.override(language):
        # a subject is one line, whatever the template's own line ends
        subject = ''.join(render_to_string(f'mail/{kind}_subject.txt', context).splitlines())
        body = render_to_string(f'mail/{kind}_body.txt', context)
    return EmailMessage(subject, body, settings.DEFAULT_FROM_EMAIL, [user.email])


def reason(failure, token):
    """Why a mail did not go out, as the users tab shows it: the error's kind and its words on one line, cut to the
    column, and never the link (an error that quotes the mail would otherwise put its token in the table)."""
    text = ' '.join(f'{type(failure).__name__}: {failure}'.split())
    text = text.replace(token, '…')
    return text if len(text) <= REASON_LENGTH else text[:REASON_LENGTH - 1] + '…'


def send(user, kind, by=None):
    """Sends `user` the mail of `kind` and records it; returns the record (`error` says why when it did not go out).
    Whatever stops a mail (no server, a refusal, a missing setting) is recorded and logged, never raised: the caller's
    own work stands."""
    language = account_language(user) or translation.get_language()
    uid, token = link_parts(user)
    error = ''
    try:
        if message(user, kind, by, language, uid, token).send(using=DEFAULT_MAILER_ALIAS) != 1:
            error = 'The mail server took no message.'
    except Exception as failure:
        error = reason(failure, token)
    if error:
        # the reason alone, not the exception: its own words may quote the mail, link and all
        logger.error('The %s mail for user %s was not sent: %s', kind, user.pk, error)
    return AccountMail.objects.create(user=user, kind=kind, address=user.email, requested_by=by, error=error)


def reset(user):
    """Sends `user` a password reset mail, unless the account has had its share for the hour
    (settings.PASSWORD_RESET_MAILS_PER_HOUR; a mail that was tried counts). Returns the record, or None when the
    request was held back: the person asking is answered the same either way, and the server's log says it. The
    account's row is locked while its mails are counted and the mail is sent, so requests that arrive together take
    turns and cannot all read "none sent yet"."""
    with transaction.atomic():
        user = get_user_model().objects.select_for_update().filter(pk=user.pk, is_active=True).first()
        if user is None:                 # deactivated since the form looked the address up
            return None
        since = timezone.now() - timedelta(hours=1)
        recent = AccountMail.objects.filter(user=user, kind=RESET, created_at__gte=since).count()
        if recent >= settings.PASSWORD_RESET_MAILS_PER_HOUR:
            logger.warning('A password reset mail for user %s was held back: %s in the last hour.', user.pk, recent)
            return None
        return send(user, RESET)


def cannot_invite(user):
    """Why `user` cannot be sent an invitation, for the admin; None when they can."""
    name = {'name': user.get_username()}
    if user.has_usable_password():
        return _('%(name)s has already set a password: they sign in with it, or ask for a new link with '
                 '“Forgot your password?”.') % name
    if not user.is_active:
        return _('%(name)s is inactive: an inactive person cannot sign in.') % name
    if not user.email:
        return _('%(name)s has no email address: add one first.') % name
    return None


@dataclass(frozen=True)
class Standing:
    """Where a person stands with their invitation, for their row on the users tab."""
    state: str            # one of the states below
    mail: object = None   # the last invitation's record, when there is one
    can_send: bool = False

    PASSWORD_SET, INACTIVE, NO_ADDRESS, NOT_INVITED = 'password_set', 'inactive', 'no_address', 'not_invited'
    NOT_SENT, ADDRESS_CHANGED, EXPIRED, SENT = 'not_sent', 'address_changed', 'expired', 'sent'


def standing(user):
    """`user`'s standing: the password set, or what became of the last invitation. Reads the invitations prefetched on
    the user as `invitations` (newest first) when the list did that, else asks."""
    if user.has_usable_password():
        return Standing(Standing.PASSWORD_SET)
    if not user.is_active:
        return Standing(Standing.INACTIVE)
    if not user.email:
        return Standing(Standing.NO_ADDRESS)
    mails = getattr(user, 'invitations', None)
    if mails is None:
        mails = AccountMail.objects.filter(user=user, kind=INVITATION).order_by('-created_at', '-id')[:1]
    last = next(iter(mails), None)
    if last is None:
        return Standing(Standing.NOT_INVITED, can_send=True)
    if last.error:
        state = Standing.NOT_SENT
    elif last.address != user.email:
        state = Standing.ADDRESS_CHANGED            # the token holds the address: that link died with the change
    elif last.created_at + timedelta(seconds=settings.PASSWORD_RESET_TIMEOUT) < timezone.now():
        state = Standing.EXPIRED
    else:
        state = Standing.SENT
    return Standing(state, last, can_send=True)
