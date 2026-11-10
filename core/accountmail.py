"""The account e-mails: the invitation a new person gets and the password reset. One path for both.

Each carries Django's own one-time link (`default_token_generator`, opened by `PasswordResetConfirmView`): it works
until the password is set, the address changes or settings.PASSWORD_RESET_TIMEOUT has passed, whichever comes first.
The link starts with settings.PUBLIC_BASE_URL, never with the Host header of the request that caused the mail, and the
mail is written in the recipient's saved language (otherwise in the language of whoever caused it). It goes out through
the default mailer (settings.MAILERS)."""
from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ImproperlyConfigured
from django.core.mail import DEFAULT_MAILER_ALIAS, EmailMessage
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import translation
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from .language import account_language
from .people import person_name

INVITATION, RESET = 'invitation', 'reset'


def public_url(path):
    """`path` of this server as people reach it from outside."""
    if not settings.PUBLIC_BASE_URL:
        raise ImproperlyConfigured('PUBLIC_BASE_URL is not set: the link in the mail would lead nowhere.')
    return settings.PUBLIC_BASE_URL + path


def set_password_link(user):
    """The one-time link that lets `user` set a password."""
    return public_url(reverse('password_reset_confirm', kwargs={
        'uidb64': urlsafe_base64_encode(force_bytes(user.pk)), 'token': default_token_generator.make_token(user)}))


def message(user, kind, by=None):
    """The mail of `kind` (INVITATION or RESET) for `user`; `by` is who invited them."""
    context = {
        'name': person_name(user), 'username': user.get_username(), 'link': set_password_link(user),
        'reset_url': public_url(reverse('password_reset')), 'hours': settings.PASSWORD_RESET_TIMEOUT // 3600,
        'company': settings.COMPANY_NAME, 'inviter': person_name(by) if by else '',
    }
    with translation.override(account_language(user) or translation.get_language()):
        # a subject is one line, whatever the template's own line ends
        subject = ''.join(render_to_string(f'mail/{kind}_subject.txt', context).splitlines())
        body = render_to_string(f'mail/{kind}_body.txt', context)
    return EmailMessage(subject, body, settings.DEFAULT_FROM_EMAIL, [user.email])


def send(user, kind, by=None):
    """Sends `user` the mail of `kind`."""
    message(user, kind, by).send(using=DEFAULT_MAILER_ALIAS)
