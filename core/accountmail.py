"""The account e-mails: the invitation a new person gets and the password reset. One path for both.

Each carries Django's own one-time link (`default_token_generator`, opened by `PasswordResetConfirmView`): it works
until the password is set, the address changes or settings.PASSWORD_RESET_TIMEOUT has passed, whichever comes first.
The link starts with settings.PUBLIC_BASE_URL, never with the Host header of the request that caused the mail, and the
mail is written in the recipient's saved language (otherwise in the language of whoever caused it). It goes out through
the default mailer (settings.MAILERS).

**A mail leaves after the request, never in it.** `AccountMail` is the outbox: what causes a mail writes its row as
waiting (`queue`), inside its own transaction, so a save that fails leaves no row and sends nothing. Once that
transaction has committed, the row is handed to the worker (`hand_over`): one background thread per process, which
talks to the mail server outside any transaction and any lock and then writes what became of the mail on its row,
sent or why not. So a request never waits for a mail server, a person's row is never locked while one is talked to,
and a mail is never out for a record that does not exist. A mail gets settings.MAIL_SEND_SECONDS in all (`_send`). A
row still waiting long after that never finished (the server stopped with the mail in its queue): it counts as not
sent, never as sent (`state`). Nothing is raised to the page that caused a mail: the person's row on the users tab says
what happened, and the server's log has the line."""
import atexit
import logging
import queue as queues
import socket
import threading
import time
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import _unicode_ci_compare
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.core.mail import DEFAULT_MAILER_ALIAS, EmailMessage, mailers
from django.db import connections, transaction
from django.db.models import CharField, OuterRef, Q, Subquery
from django.db.models.functions import Cast
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone, translation
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.utils.translation import gettext as _, gettext_noop

from . import audit
from .language import account_language
from .models import AccountMail, AuditLog
from .people import person_name

logger = logging.getLogger(__name__)

INVITATION, RESET = AccountMail.Kind.INVITATION, AccountMail.Kind.RESET
REASON_LENGTH = AccountMail._meta.get_field('error').max_length

# Why a mail did not go out, in the platform's own words (a mail server's own are kept as it said them).
TOOK_NOTHING = 'The mail server took no message.'
NO_PUBLIC_ADDRESS = 'The public address of this server is not set (PUBLIC_BASE_URL): the link would lead nowhere.'
TOO_SLOW = 'The mail server did not finish in time.'
BUSY = 'Too many mails are waiting to be sent.'
CHANGED = 'The account changed before the mail was sent.'
INTERRUPTED = 'The sending was interrupted: the server stopped, or the mail server never answered.'

# An invitation in the activity log: the labels and the outcome the platform writes, stored as msgids (the admin's own
# row is core.resources.UserResource.invite's).
INVITATION_LABEL, SENT_TO_LABEL = gettext_noop('Invitation'), gettext_noop('Sent to')
REASON_LABEL, NOT_SENT = gettext_noop('Reason'), gettext_noop('Not sent')
# A password set through a link, in the activity log (core.views.SetPasswordView): the address the link went to.
LINK_SENT_TO_LABEL = gettext_noop('Link sent to')


class NotSent(Exception):
    """A mail the platform itself could not send; its text is one of the sentences above."""


# --- the worker ---------------------------------------------------------------------------------------------

QUEUE_SIZE = 200          # jobs that may wait; more are refused (`background` says so), never piled up without end


class Worker:
    """One background thread of this process that runs the jobs handed to it, one after the other. It starts with the
    first job (never at import: a server that forks its processes gives each its own). A job's fault is logged and the
    worker goes on; its database connection is closed after every job, so none stays open between mails."""

    def __init__(self):
        self.jobs = queues.Queue(maxsize=QUEUE_SIZE)
        self.thread = None
        self.starting = threading.Lock()

    def put(self, job, *args):
        """Queues `job(*args)`; False when the queue is full."""
        with self.starting:
            if self.thread is None or not self.thread.is_alive():
                self.thread = threading.Thread(target=self.run, name='account-mail', daemon=True)
                self.thread.start()
        try:
            self.jobs.put_nowait((job, args))
        except queues.Full:
            return False
        return True

    def run(self):
        while True:
            job, args = self.jobs.get()
            try:
                job(*args)
            except Exception as fault:
                # the fault's kind and words: a job's own failures are recorded by the job (`deliver`)
                logger.error('A background job of the account e-mails failed: %s: %s', type(fault).__name__, fault)
            finally:
                connections.close_all()
                self.jobs.task_done()

    def drain(self, seconds):
        """Waits until every job handed over is done, at most `seconds`; whether they all are."""
        deadline = time.monotonic() + seconds
        with self.jobs.all_tasks_done:
            while self.jobs.unfinished_tasks:
                left = deadline - time.monotonic()
                if left <= 0:
                    return False
                self.jobs.all_tasks_done.wait(left)
        return True


worker = Worker()
# A server that stops in order gives the mails under way their time; one that is killed leaves their rows waiting,
# which the users tab shows as not sent.
atexit.register(lambda: worker.drain(settings.MAIL_SEND_SECONDS))


def background(job, *args):
    """Runs `job(*args)` after the request: on the worker, or at once where settings.MAIL_IN_BACKGROUND is off (the
    tests, whose uncommitted rows no other thread could read). False when the worker's queue is full."""
    if settings.MAIL_IN_BACKGROUND:
        return worker.put(job, *args)
    job(*args)
    return True


# --- the mail -----------------------------------------------------------------------------------------------

def public_url(path):
    """`path` of this server as people reach it from outside."""
    if not settings.PUBLIC_BASE_URL:
        raise NotSent(NO_PUBLIC_ADDRESS)
    return settings.PUBLIC_BASE_URL + path


class AccountTokens(PasswordResetTokenGenerator):
    """Django's one-time token, with the account's `is_active` among what it signs. Django's own value holds the id,
    the password, the last sign-in and the address, so a link ends when the password is set, the person signs in or
    the address changes; with this, deactivating an account ends its links too (an inactive account could otherwise
    be given a password through a link sent before, to be used the day it is active again). An account made active
    again within the link's lifetime has the link back: the admin who reactivates it sees its row."""

    def _make_hash_value(self, user, timestamp):
        return f'{super()._make_hash_value(user, timestamp)}{user.is_active}'


tokens = AccountTokens()      # the one generator: the links are made with it here and checked with it by SetPasswordView


def link_parts(user):
    """What the one-time link for `user` is made of: the person's id as the link carries it, and the token."""
    return urlsafe_base64_encode(force_bytes(user.pk)), tokens.make_token(user)


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
    """Why a mail did not go out, as the users tab shows it: the platform's own sentence, or the error's kind and its
    words on one line, cut to the column, and never the link (an error that quotes the mail would otherwise put its
    token in the table)."""
    if isinstance(failure, NotSent):
        return str(failure)
    text = ' '.join(f'{type(failure).__name__}: {failure}'.split())
    text = text.replace(token, '…')
    return text if len(text) <= REASON_LENGTH else text[:REASON_LENGTH - 1] + '…'


def _cut(mailer):
    """Ends the SMTP conversation `mailer` is in, whatever step it waits at (Django's SMTP backend keeps its
    connection in these two attributes; another backend has none, and nothing to cut)."""
    for name in ('connection', '_partial_connection'):
        sock = getattr(getattr(mailer, name, None), 'sock', None)
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


def _send(mail):
    """Hands `mail` to the default mailer, with settings.MAIL_SEND_SECONDS for the whole conversation: the mailer's
    own timeout is for each step of it (connect, greeting, sender, recipient, data, ...), so a server answering every
    step just in time would otherwise hold a mail many times that. Past the limit the conversation is cut off, and
    again until the send has returned (a connection still being opened has no socket to cut yet)."""
    mailer = mailers[DEFAULT_MAILER_ALIAS]
    done, late = threading.Event(), threading.Event()

    def watch():
        if not done.wait(settings.MAIL_SEND_SECONDS):
            late.set()
            while not done.wait(0.1):
                _cut(mailer)

    threading.Thread(target=watch, name='account-mail-limit', daemon=True).start()
    try:
        taken = mailer.send_messages([mail])
    except Exception:
        if late.is_set():
            raise NotSent(TOO_SLOW) from None
        raise
    finally:
        done.set()
    if taken != 1:
        raise NotSent(TOO_SLOW if late.is_set() else TOOK_NOTHING)


# --- the outbox ---------------------------------------------------------------------------------------------

def queue(user, kind, by=None):
    """Writes the mail of `kind` for `user` as waiting and returns its row. Call it inside the transaction of what
    causes the mail, and `hand_over` the row once that has committed."""
    return AccountMail.objects.create(user=user, kind=kind, address=user.email, requested_by=by)


def hand_over(mail):
    """Gives a waiting mail to the worker, after the transaction that wrote it has committed and outside any lock.
    The language of whoever caused it goes along, for a recipient who has saved none. A mail the worker cannot take
    (its queue is full) is marked not sent here; whether it was taken."""
    if background(deliver, mail.pk, translation.get_language()):
        return True
    _close(mail, BUSY, audit.message(BUSY))
    return False


def deliver(mail_id, language):
    """The worker's job: sends a waiting mail and writes what became of it. Whatever stops the mail (no server, a
    refusal, a missing setting, the time limit) is its row's reason, never raised."""
    mail = (AccountMail.objects.select_related('user', 'requested_by')
            .filter(pk=mail_id, sent_at=None, error='').first())
    if mail is None:
        return
    user = mail.user
    uid, token = link_parts(user)
    try:
        if user.email != mail.address or not user.is_active:
            raise NotSent(CHANGED)
        _send(message(user, mail.kind, mail.requested_by, account_language(user) or language, uid, token))
    except Exception as failure:
        _close(mail, reason(failure, token), kind(failure))
    else:
        AccountMail.objects.filter(pk=mail.pk, sent_at=None, error='').update(sent_at=timezone.now())


def kind(failure):
    """What the activity log says of a mail that did not go out: the platform's own sentence (a value the log shows
    in each language), or of anything else the error's kind alone. A mail server's own words can name its relay
    hosts and its account, and the log is read by whoever a role lets; they stay on the mail's row, which the
    platform admin reads on the users tab."""
    return audit.message(str(failure)) if isinstance(failure, NotSent) else type(failure).__name__


def _close(mail, error, what):
    """Marks a waiting mail as not sent: `error` on its row and in the server's log and, for an invitation, the
    platform's own line in the activity log after the admin's "Invited", with `what` kind of failure it was
    (`kind`)."""
    if not AccountMail.objects.filter(pk=mail.pk, sent_at=None, error='').update(error=error):
        return
    # the reason alone, not the exception: its own words may quote the mail, link and all
    logger.error('The %s mail %s for user %s was not sent: %s', mail.kind, mail.pk, mail.user_id, error)
    if mail.kind == INVITATION:
        with audit.source_language():
            changes = {str(INVITATION_LABEL): [None, audit.message(NOT_SENT)],
                       str(SENT_TO_LABEL): [None, mail.address], str(REASON_LABEL): [None, what]}
        audit.record(None, AuditLog.Action.INVITE, mail.user, changes,
                     entity_type=audit.entity_type_of(get_user_model()))



def reset_later(address):
    """What "Forgot your password?" does with an address, and all it does in the request: it hands the address (and
    the language it was asked in) to the worker. Whether the address has an account, whether that account has had its
    share, whether the mail goes out: none of it happens before the answer, so the answer takes the same time and the
    same work for every address."""
    if not background(reset_now, address, translation.get_language()) and _tell(dropped_told, 'requests', 60):
        logger.error('Password reset requests are being dropped: too many mails are waiting to be sent.')


def accounts_on(address):
    """The accounts a reset mail for `address` goes to: the active ones whose address it is, whatever its case."""
    users = get_user_model().objects.filter(email__iexact=address, is_active=True)
    return [user for user in users if _unicode_ci_compare(address, user.email)]


# How long a reset mail that did not go out counts against its account's hour: long enough that a mail server which
# is down is not tried for every request, short enough that nobody is kept out for an hour by mails that never came.
FAILED_COUNTS_FOR = timedelta(minutes=5)
# When the server's log last said that an account's requests are held back, and that requests are dropped: once an
# hour for an account and once a minute, not a line for every request anybody sends (this process's own memory).
held_told, dropped_told = {}, {}


def _tell(told, key, seconds):
    """Whether the log should say it (again): not said for `key` within `seconds`."""
    last, now = told.get(key), time.monotonic()
    if last is not None and now - last < seconds:
        return False
    told[key] = now
    return True


def held_back(user):
    """Whether `user` has had the reset mails of an hour (settings.PASSWORD_RESET_MAILS_PER_HOUR): the ones that
    went out or are waiting, and the ones that failed in the last five minutes. Said in the server's log, once an
    hour for the account."""
    now = timezone.now()
    recent = AccountMail.objects.filter(user=user, kind=RESET, created_at__gte=now - timedelta(hours=1)).filter(
        Q(error='') | Q(created_at__gte=now - FAILED_COUNTS_FOR)).count()
    if recent < settings.PASSWORD_RESET_MAILS_PER_HOUR:
        return False
    if _tell(held_told, user.pk, 3600):
        logger.warning('Password reset mails for user %s are held back: %s in the last hour.', user.pk, recent)
    return True


def reset_now(address, language):
    """The worker's job for a reset: each account on `address` is sent a reset mail, unless it has had its share for
    the hour (`held_back`).
    The account's row is locked only while its mails are counted and the new one is written as waiting, so two server
    processes at one account take turns and cannot both read "none yet"; the mail server is talked to after the lock
    is gone."""
    for user in accounts_on(address):
        with transaction.atomic():
            get_user_model().objects.select_for_update().get(pk=user.pk)
            if held_back(user):
                continue
            mail = queue(user, RESET)
        deliver(mail.pk, language)


# --- where a person stands, for the users tab -----------------------------------------------------------------

WAITING, SENT, FAILED = 'waiting', 'sent', 'failed'


def state(mail):
    """What became of a mail: SENT, FAILED, or WAITING while the worker may still have it. A row waiting longer than
    a mail can take (twice the limit: the worker may have been at another mail) never finished, and is FAILED."""
    if mail.error:
        return FAILED
    if mail.sent_at:
        return SENT
    over = mail.created_at + timedelta(seconds=2 * settings.MAIL_SEND_SECONDS) < timezone.now()
    return FAILED if over else WAITING


def shown_reason(mail):
    """Why a mail did not go out, for a page: its row's reason, or that it never finished."""
    return mail.error or INTERRUPTED


def being_sent(user):
    """Whether an invitation for `user` is waiting with the worker right now."""
    last = AccountMail.objects.filter(user=user, kind=INVITATION).order_by('-created_at', '-id').first()
    return last is not None and state(last) == WAITING


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
    if being_sent(user):
        return _('An invitation to %(name)s is being sent right now: wait for it, the row says what became of it.') % name
    return None


def password_sets():
    """The activity log's rows of a password set through a link, newest first, for a users queryset to read each
    account's last one from (`with_password_set`)."""
    return AuditLog.objects.filter(
        action=AuditLog.Action.PASSWORD, entity_type=audit.entity_type_of(get_user_model()),
        entity_id=Cast(OuterRef('pk'), CharField())).order_by('-created_at')


def with_password_set(users):
    """`users` with when each last set a password through a link and what the log says of it."""
    return users.annotate(password_set_at=Subquery(password_sets().values('created_at')[:1]),
                          password_set_changes=Subquery(password_sets().values('changes')[:1]))


def password_set(user):
    """(when, the address the link went to) of the last password `user` set through a link; (None, '') when the
    password was not set through one. Read from what `with_password_set` put on the user, else asked."""
    if hasattr(user, 'password_set_at'):
        when, changes = user.password_set_at, user.password_set_changes
    else:
        when, changes = (AuditLog.objects.filter(
            action=AuditLog.Action.PASSWORD, entity_type=audit.entity_type_of(get_user_model()),
            entity_id=str(user.pk)).values_list('created_at', 'changes').first() or (None, None))
    return when, ((changes or {}).get(LINK_SENT_TO_LABEL) or [None, ''])[1] or ''


@dataclass(frozen=True)
class Standing:
    """Where a person stands with their invitation, for their row on the users tab."""
    state: str            # one of the states below
    mail: object = None   # the last invitation's record, when there is one
    can_send: bool = False
    reason: str = ''      # why it was not sent, for NOT_SENT
    set_at: object = None  # for PASSWORD_SET: when it was set through a link (None: not through one)
    link_address: str = ''  # and the address that link went to, when the account's is another now

    PASSWORD_SET, INACTIVE, NO_ADDRESS, NOT_INVITED = 'password_set', 'inactive', 'no_address', 'not_invited'
    SENDING, NOT_SENT, ADDRESS_CHANGED, EXPIRED, SENT = 'sending', 'not_sent', 'address_changed', 'expired', 'sent'


def standing(user):
    """`user`'s standing: the password set, or what became of the last invitation. Reads the invitations prefetched on
    the user as `invitations` (newest first) when the list did that, else asks."""
    if user.has_usable_password():
        set_at, address = password_set(user)
        return Standing(Standing.PASSWORD_SET, set_at=set_at, link_address='' if address == user.email else address)
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
    became = state(last)
    if became == WAITING:
        return Standing(Standing.SENDING, last)
    if became == FAILED:
        return Standing(Standing.NOT_SENT, last, can_send=True, reason=shown_reason(last))
    if last.address != user.email:
        found = Standing.ADDRESS_CHANGED            # the token holds the address: that link died with the change
    elif last.sent_at + timedelta(seconds=settings.PASSWORD_RESET_TIMEOUT) < timezone.now():
        found = Standing.EXPIRED
    else:
        found = Standing.SENT
    return Standing(found, last, can_send=True)
