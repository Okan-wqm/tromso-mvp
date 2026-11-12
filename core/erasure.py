"""Erasing, on request, an address an invitation was mis-sent to (docs/erasure.md, step 8; the owner's decision of
2026-11-11: yes, the activity log is changed for this).

The platform admin mistypes a new person's address; the invitation goes to whoever has that address, and the address
then stays in two places after the account's own address has been put right: the table `account_mails` (one row per
mail sent or tried: `address`, and `error` where a mail server's reply repeats it) and the activity log's rows of that
account (Created and Changed: `Email`; Invited: `Sent to`; Password set: `Link sent to`). `erase` replaces it in both,
in one transaction, and writes one new log row on each account it touched: "Erased on request", with the instruction
it was done on and who carried it out (in the log's own shape, so it reads in the reader's language). It is the one writer that changes rows of the log after core/0011: the log is
append-only by a trigger, which is set aside for these updates only, inside the transaction, and is back in force
when it ends, however it ends.

What it is and is not:
- **Erasure, not pseudonymisation.** The address is replaced by a placeholder that says nothing about it: in
  `account_mails` the address `erased@invalid` (the column holds an address; `.invalid` can never be one), in the log
  the enumerated value "Erased on request" (shown in the reader's language, with no digest: core/0011's private values
  keep a keyed digest of what they hide, this keeps nothing).
- **The log stays honest.** The rows stay, with who did what and when: an invitation went out, a link was used, an
  address was changed. Only to which address is gone. The users tab says so in its own words
  (core.accountmail.Standing: `link_erased`, `mail_erased`).
- **What it checks, and what it cannot.** It refuses an address that is the address of any account NOW (whatever its
  case, the spaces around it, the account active or not), and refuses while a mail to it is still with the mail
  worker. That is all it checks. It cannot tell a stranger's address from an address that was a person's own for a
  year, or from one an intruder put on an account and took off again: all three are "an address an account once had".
  So `plan` gathers what the log says of each account touched (`History`: from when to when the address was the
  account's own, whether it replaced an earlier address, whether a password was set through a link sent to it, what
  the account wrote meanwhile, counted by the account's key and so whatever its name was or is) and says plainly when
  it does not look like a stranger's: always when it replaced an earlier address of the account and a password was
  set through a link sent to it, which is how an account is taken over. The data-protection officer decides; the
  command informs and obeys.
- **Only that address.** A value is replaced when it is that address and nothing else, under those labels, on rows of
  user accounts; inside a mail server's reply (`account_mails.error`) the address is replaced where it stands as a
  whole address, in any case and Unicode form, never as a part of a longer one. Whatever else holds the text is listed
  for the operator and left as it is: another label or another shape of value on a user's row, another kind of record,
  an account's username, the name a log row is under or was written by. No step of the procedure changes those last
  three. What the list cannot see: a reply that names the address in another form (cut off by the column's length,
  rewritten by a mailing system as `name=domain@bounce...`).
- **Nothing it writes holds the address.** The instruction and the name of who carries it out are refused when they
  hold it anywhere, as a part of a longer word or address too (`written_holds`: they would put it back into the log,
  where this command would not find it again), and its own rows are written under the account's number when the
  account's username holds it. That refusal refuses rather once too often.
- **The Turkish capital İ and the dotless ı.** An address is compared as Django compares one (`_folded`: case folded,
  one Unicode form), and to that `İNFO@EXAMPLE.COM` and `info@example.com` are two addresses: a capital İ folds to
  an i with a dot above it, and ı is a letter of its own. What is replaced is decided by that comparison alone, so
  nothing is erased that is another address by it. Read more widely (`_loose`: both read as i) are only the
  questions where once too often costs nothing: whether what the command writes holds the address, whether an account
  has it now, and which rows the dry run points at as holding it only when read so (`Plan.near`: named, left as they
  are; the operator runs the command with the address as it is stored when it is the same one).
- **It does not hold up the log for long.** Everything is read before any lock is taken. The log is then locked
  against writers with a bounded wait (`LOCK_WAIT_SECONDS`): when the lock cannot be had in that time the erasure is
  refused, and no writer has waited behind it for longer. Holding it, the erasure waits for `account_mails` and for
  the rows of it to rewrite only a moment, a quarter of the server's deadlock timeout each (`_mails_wait`: 250 ms as
  PostgreSQL ships), and is refused otherwise (a mail is being written just then). So it gives up before a session
  that waits behind its lock on the log looks for a deadlock, and never stands in one with the mail worker, which
  writes a mail's row and then the log; and the instant something else holds the table (the database's own vacuum or
  analyze, the mail worker saying it still has a mail) does not refuse the run, as taking the lock at once or not at
  all did. Under the locks it
  reads again what must not have changed (the refusals, the rows of the log to rewrite, that no row of a user account
  was added, and every mail: the same rows hold the address as when it was read, none other) and writes. Every writer
  of the log, the alarms among them, and of `account_mails` waits for that short moment.
- **Not undone, and not complete beyond the database**: backups hold the address as they hold everything else.

`plan` reads only; `erase` writes. The command `manage.py erase_stranger_address` is the only caller: no page does
this (it removes the evidence of where a link went, so the data-protection officer decides each case)."""
import json
import math
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import OperationalError, connection, transaction
from django.db.models import Q
from django.utils.translation import gettext_noop

from . import accountmail, audit
from .models import AccountMail, AuditLog

TRIGGER = 'trg_audit_log_append_only'
ERASED_ADDRESS = accountmail.ERASED_ADDRESS
ERASED = accountmail.ERASED
# The erasure's own row, in the log's own shape: a label with an enumerated value, both shown in the reader's language
# (AuditLog.shown_changes), then the two things a person typed, each under a label of its own. The log has no
# translated sentence with parameters, and none is invented for this: the row reads "Erased on request: The address
# of a mis-sent invitation; Instruction: ...; Carried out by: ...".
ERASED_LABEL = gettext_noop('Erased on request')
WHAT = gettext_noop('The address of a mis-sent invitation')
INSTRUCTION_LABEL, BY_LABEL = gettext_noop('Instruction'), gettext_noop('Carried out by')
# How long the erasure waits for the lock on the log (and for a row of account_mails) before it is refused: every
# writer of the log queues behind a session that waits for this lock, so the wait is bounded.
LOCK_WAIT_SECONDS = 5
# A mistyped address is put right soon: one that was an account's own for at least this long is said to look like a
# person's own former address.
OWN_FOR_LONG = timedelta(days=1)


def labels():
    """The labels the log keeps an account's address under, as the code writes them (English at rest)."""
    from .forms import UserForm
    return (audit.english(UserForm.Meta.labels['email']), audit.english(accountmail.SENT_TO_LABEL),
            audit.english(accountmail.LINK_SENT_TO_LABEL))


def user_type():
    return audit.entity_type_of(get_user_model())


def _folded(text):
    """An address as it is compared: without the spaces around it, case folded, in one Unicode form (as Django
    compares the address of a password reset)."""
    return unicodedata.normalize('NFKC', str(text).strip()).casefold()


def _loose(text):
    """`_folded`, with the Turkish i's read as one letter: the capital İ (it folds to an i with a dot above it, U+0307)
    and the dotless ı both become i. Wider than an address is compared by, and never what decides a replacement: for
    the questions where once too often costs nothing (the module's words, The Turkish capital İ)."""
    return _folded(text).replace('\u0307', '').replace('ı', 'i')


def same(one, other):
    return isinstance(one, str) and _folded(one) == _folded(other)


def inside(address):
    """The pattern of `address` standing as a whole address inside a longer text (a mail server's reply), whatever
    its case: not as the tail of a longer local part (`anna@x.no` when `a@x.no` is asked for) nor the head of a
    longer domain (`a@x.no.example`). A quotation mark before it is the reply's own (`{'a@x.no': (550, ...)}`, as
    Python writes a refused recipient), not a part of the address.

    **It finds candidates, it does not decide.** Ignoring case, Python reads more letters as one than the comparison
    of addresses does: the Turkish capital İ and the dotless ı match `i` (and ſ `s`, the Kelvin sign `k`). So what it
    finds is compared as addresses are (`same`, or the caller's fold) before it is replaced or said to hold the
    address: `_without` and `holds` do, and nothing else reads this pattern."""
    return re.compile(r'(?<![\w.+%-])' + re.escape(address.strip()) + r'(?![\w-]|\.\w)', re.IGNORECASE)


def _leaves(value):
    """Every text inside a stored value, whatever its shape (a pair, a list in a list, an enumerated value)."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for inner in value.values():
            yield from _leaves(inner)
    elif isinstance(value, (list, tuple)):
        for inner in value:
            yield from _leaves(inner)


def _without(address, error):
    """A mail server's reply with the address replaced wherever `holds` finds it (as written, and every address-like
    run that is the address in another case or Unicode form; a closing full stop stays), cut to the column as a reason
    is (the placeholder can be longer than the address it stands for)."""
    def other_form(found):
        token = found.group()
        core = token.rstrip('.')
        return ERASED_ADDRESS + token[len(core):] if same(core, address) else token

    def as_compared(found):                  # the pattern's candidate, replaced only when it is the address (`inside`)
        return ERASED_ADDRESS if same(found.group(), address) else found.group()

    text = TOKEN.sub(other_form, inside(address).sub(as_compared, error))
    return text if len(text) <= accountmail.REASON_LENGTH else text[:accountmail.REASON_LENGTH - 1] + '…'


# A run of the characters an address is usually made of, around an "@": what `holds` reads as one address in a text.
TOKEN = re.compile(r'[\w.+%-]+@[\w.-]+')


def holds(text, address, fold=_folded):
    """Whether `text` holds `address` as a whole address, compared as addresses are compared here: in any case and
    Unicode form (`_folded`; `fold=_loose` reads the Turkish i's as one letter too), and inside a longer text (`inside`,
    and every address-like run of the text by itself, its closing full stops aside)."""
    if not isinstance(text, str):
        return False
    wanted = fold(address)
    return any(fold(found.group()) == wanted for found in inside(wanted).finditer(fold(text))) or any(
        fold(found.group().rstrip('.')) == wanted for found in TOKEN.finditer(text))


def written_holds(text, address):
    """Whether a text the command itself writes (the instruction, the name, the label of its row) holds the address in
    ANY way: the address anywhere in it, as a part of a longer word or of a longer address too, both read loosely
    (`_loose`). `strangr@example.com.Confirmed`, `strangr@example.com-DP17`, `ref.strangr@example.com` and
    `xstrangr@example.com` all hold it. Once too often costs a rewording; once too seldom puts the address back into
    the log, where no run finds it again."""
    return isinstance(text, str) and _loose(address) in _loose(text)


def holders(address):
    """The accounts whose own address `address` is now, active or not; read loosely (`_loose`): an account whose address
    is this one but for a Turkish capital İ or a dotless ı counts, since refusing once too often costs nothing here."""
    wanted = _loose(address)
    return [user for user in get_user_model().objects.exclude(email='').order_by('pk') if _loose(user.email) == wanted]


@dataclass
class History:
    """What the log says of one account and the address: for the data-protection officer to judge the case by."""
    account: int
    name: str
    own: list = field(default_factory=list)          # [(from, how, until or None, how)]: when it was the account's own
    replaced: list = field(default_factory=list)     # [(when, how)]: a row put it in place of an earlier address
    passwords: list = field(default_factory=list)    # [(when, who)]: a password set through a link sent to it
    invitations: list = field(default_factory=list)  # [(when, who)]: an invitation sent, or tried, to it
    used: int = 0                                    # other log rows the account itself wrote while it was its address
    names: set = field(default_factory=set)          # every name the account's rows are under (it can be renamed)

    @property
    def longest(self):
        return max((until - start for start, _how, until, _end in self.own if until is not None), default=None)

    @property
    def warnings(self):
        """Why this does not look like a stranger's address; [] when nothing in the log says so."""
        found = []
        if self.replaced and self.passwords:        # whatever the durations: minutes are enough to take an account over
            found.append('it replaced an earlier address of the account and a password was set through a link sent to '
                         'it, which is how an account is taken over through a changed address')
        if self.longest is not None and self.longest >= OWN_FOR_LONG:
            found.append(f'it was the account’s own address for {self.longest.days} day(s)')
        if any(until is None for _start, _how, until, _end in self.own):
            found.append('the log does not say when it stopped being the account’s own address')
        if self.used:
            found.append(f'the account wrote {self.used} other log row(s) itself while it was its address')
        if len(self.passwords) > 1:
            found.append(f'{len(self.passwords)} passwords were set through links sent to it')
        return found


@dataclass
class Plan:
    """What an erasure of `address` would change, and what else holds its text."""
    address: str
    mails: list = field(default_factory=list)       # [(AccountMail, address replaced?, the error as it would be or None)]
    entries: list = field(default_factory=list)     # [(AuditLog, the labels changed, its changes as they would be)]
    elsewhere: list = field(default_factory=list)   # [words]: where else the text stands, left as it is
    near: list = field(default_factory=list)        # [words]: rows holding it only with the Turkish i's read as one
    held_by: list = field(default_factory=list)     # the accounts whose own address it is: the erasure is refused
    waiting: list = field(default_factory=list)     # mails to it still with the mail worker: the erasure is refused
    stored: dict = field(default_factory=dict)      # {(kind, row id): the value as stored}, where not as typed
    histories: list = field(default_factory=list)   # a History per account touched
    user_rows: int = 0                              # how many rows of user accounts the log held when this was read
    mail_rows: int = 0                              # ... and how many rows account_mails held

    @property
    def accounts(self):
        """The ids of the accounts whose rows would change, in order."""
        found = [mail.user_id for mail, _address, _error in self.mails]
        found += [int(entry.entity_id) for entry, _labels, _changes in self.entries if entry.entity_id.isdigit()]
        return sorted(set(found))

    @property
    def empty(self):
        return not self.mails and not self.entries


def _mails(found):
    """Reads every row of account_mails into the Plan `found`: the rows to change, the waiting ones, the values stored
    otherwise than typed, the near matches, and how many rows there are. `plan` reads them so, and `_still` again under
    the locks, to compare."""
    address = found.address
    mails = list(AccountMail.objects.select_related('user').order_by('pk'))
    found.mail_rows = len(mails)
    for mail in mails:
        mine = same(mail.address, address)
        error = _without(address, mail.error) if holds(mail.error, address) else None
        if mine or error is not None:
            found.mails.append((mail, mine, error))
        if mine and mail.address != found.address:
            found.stored[('mail', mail.pk)] = mail.address
        if mine and accountmail.state(mail) == accountmail.WAITING:
            found.waiting.append(mail)
        left = ([] if mine else [('address', mail.address)]) + [('error', mail.error if error is None else error)]
        near = [what for what, text in left if holds(text, address, _loose)]
        if near:
            found.near.append(f'account_mails {mail.pk} ({mail.kind} for account {mail.user_id}): {" and ".join(near)}'
                              + (f' (“{mail.address}”)' if 'address' in near else ''))
    return found


def _mails_as_read(found):
    """What `_still` compares: each row to change with what it held and what it becomes."""
    return {mail.pk: (mail.address, mail.error, mail.sent_at, mine, error) for mail, mine, error in found.mails}


def plan(address):
    """The Plan for `address`. Reads only, and takes no lock."""
    found = _mails(Plan(address.strip(), held_by=holders(address)))
    own = labels()
    rows = list(AuditLog.objects.filter(entity_type=user_type()).order_by('created_at', 'id'))
    found.user_rows = len(rows)
    for entry in rows:
        changes, changed = dict(entry.changes or {}), []
        for label, pair in changes.items():
            if label in own and isinstance(pair, list) and any(same(value, address) for value in pair):
                as_stored = sorted({value for value in pair if same(value, address) and value != found.address})
                if as_stored:
                    found.stored[('entry', entry.pk)] = ', '.join(as_stored)
                changes[label] = [ERASED if same(value, address) else value for value in pair]
                changed.append(label)
        left = [label for label, value in changes.items() if any(holds(leaf, address) for leaf in _leaves(value))]
        if left:                      # whatever of it is left on the row once the pairs above are replaced
            found.elsewhere.append(f'activity log {entry.pk} ({entry.action} of user {entry.entity_label}): under '
                                   + ', '.join(f'“{label}”' for label in left)
                                   + ' (another label, or a shape of value this command does not change)')
        near = {label: sorted({leaf for leaf in _leaves(value) if _loose(leaf) == _loose(address)})
                for label, value in changes.items()
                if label not in left and any(holds(leaf, address, _loose) for leaf in _leaves(value))}
        if near:
            found.near.append(f'audit_log {entry.pk} ({entry.action} of user {entry.entity_label}): under '
                              + ', '.join(f'“{label}”' + (f' (“{", ".join(stored)}”)' if stored else '')
                                          for label, stored in near.items()))
        if changed:
            found.entries.append((entry, changed, changes))
    found.elsewhere += _elsewhere(address)
    found.histories = _histories(found, rows, address, own)
    return found


def _histories(found, rows, address, own):
    """What the log says of each account touched (History), read from the rows of user accounts already in hand, and
    one count per time the address was the account's own."""
    email, sent_to, link_to = own
    touched = {str(pk) for pk in found.accounts}
    histories = {}
    for entry in rows:
        if entry.entity_id not in touched:
            continue
        history = histories.setdefault(entry.entity_id, History(int(entry.entity_id), entry.entity_label))
        history.name = entry.entity_label
        history.names.add(entry.entity_label)
        changes, how = entry.changes or {}, f'{entry.action} by {entry.user_name}'
        pair = changes.get(email)
        if isinstance(pair, list) and len(pair) == 2:
            if same(pair[1], address):
                history.own.append((entry.created_at, how, None, None))
                if pair[0] not in (None, '') and not same(pair[0], address):      # the account had another address before
                    history.replaced.append((entry.created_at, how))
            elif same(pair[0], address) and history.own and history.own[-1][2] is None:
                history.own[-1] = (*history.own[-1][:2], entry.created_at, how)
        if isinstance(changes.get(link_to), list) and any(same(value, address) for value in changes[link_to]):
            history.passwords.append((entry.created_at, entry.user_name))
        if isinstance(changes.get(sent_to), list) and any(same(value, address) for value in changes[sent_to]):
            history.invitations.append((entry.created_at, entry.user_name))
    for history in histories.values():
        # What the account itself wrote: by the row's key of who wrote it, so a rename loses nothing; a row without the
        # key (its writer's account is not named by one) counts under any name the account's own rows carry.
        by_account = Q(user_id=history.account) | Q(user__isnull=True, user_name__in=history.names)
        for start, _how, until, _end in history.own:
            written = AuditLog.objects.filter(by_account, created_at__gte=start).exclude(
                action=AuditLog.Action.PASSWORD, entity_type=user_type(), entity_id=str(history.account))
            history.used += (written.filter(created_at__lt=until) if until is not None else written).count()
    return [histories[key] for key in sorted(histories, key=int)]


def _elsewhere(address):
    """Where else the text of the address stands, for the operator to see: the name a log row is under or was written
    by, a row of another kind of record, an account's username. A search of the text as stored (then read as `holds`
    reads it): an address holding a quotation mark or a backslash is written otherwise in the log's JSON and is not
    found by it."""
    text, found = address.strip(), []
    for user in get_user_model().objects.filter(username__icontains=text).order_by('pk'):
        if holds(user.username, address):
            found.append(f'the username of account {user.pk} ({user.username})')
    named = AuditLog.objects.filter(entity_label__icontains=text) | AuditLog.objects.filter(user_name__icontains=text)
    count = sum(1 for entry in named.only('entity_label', 'user_name')
                if holds(entry.entity_label, address) or holds(entry.user_name, address))
    if count:
        found.append(f'{count} activity-log row(s) written under or by that name (the record’s label, the user’s name)')
    others = AuditLog.objects.exclude(entity_type=user_type()).filter(changes__icontains=text).order_by('created_at', 'id')
    for entry in others.only('entity_type', 'entity_label', 'action', 'changes'):
        if holds(json.dumps(entry.changes, ensure_ascii=False), address):
            found.append(f'activity log {entry.pk} ({entry.action} of {entry.entity_type} {entry.entity_label})')
    return found


class Refused(Exception):
    """An erasure that is not done, with why."""


def trigger_in_force(cursor):
    """Whether the log's append-only trigger is there and fires for ordinary sessions."""
    cursor.execute("SELECT tgenabled FROM pg_trigger WHERE tgname = %s AND tgrelid = 'audit_log'::regclass", [TRIGGER])
    return [row[0] for row in cursor.fetchall()] == ['O']


def refuse_words(address, instruction, by):
    """Nothing this command writes may hold the address: the instruction and the name are written in its own row."""
    for what, text in (('--instruction', instruction), ('--carried-out-by', by)):
        if written_holds(text, address):
            raise Refused(f'{what} holds the address itself (anywhere in it, as a part of a longer word or address '
                          f'too). It is written into the activity log, where the address would then stand again and '
                          f'this command would not find it: give the instruction’s reference and date (and your name) '
                          f'without the address.')


def held_by_names(found):
    """The accounts that have the address now, each with its address as stored when that is the asked one only with
    the Turkish i's read as one letter (`holders`)."""
    return ', '.join(user.get_username() + ('' if same(user.email, found.address) else f', as “{user.email}”')
                     for user in found.held_by)


def _refuse(found):
    if found.held_by:
        raise Refused(f'{found.address} is the address of an account now ({held_by_names(found)}). This command erases '
                      f'only an address that no account has now; an account’s own address is kept (docs/erasure.md, '
                      f'What remains in plain text).')
    if found.waiting:
        raise Refused(f'A mail to {found.address} is being sent right now (account_mails '
                      f'{", ".join(str(mail.pk) for mail in found.waiting)}): its row is about to say what became '
                      f'of it. Run this again when it has.')


CHANGED_MEANWHILE = ('The rows this would change were changed, or new ones were written, while it was being prepared: '
                     'nothing was changed. Run it again.')


def _still(found, cursor):
    """Under the locks: what was read before them is still so. That no account has the address now; that neither the
    log's rows of user accounts got a row meanwhile (one that could hold the address) nor the rows to rewrite changed;
    and the mails, all of them read again as `plan` read them: the same rows hold the address, with the same values,
    and none other does (a mail outside the plan whose reply came to hold it meanwhile refuses the run as a new row
    does)."""
    held_by = holders(found.address)
    if held_by:
        found.held_by = held_by
        _refuse(found)
    cursor.execute('SELECT count(*) FROM audit_log WHERE entity_type = %s', [user_type()])
    if cursor.fetchone()[0] != found.user_rows:
        raise Refused(CHANGED_MEANWHILE)
    as_read = {entry.pk: entry.changes for entry, _labels, _changes in found.entries}
    if as_read and dict(AuditLog.objects.filter(pk__in=as_read).values_list('pk', 'changes')) != as_read:
        raise Refused(CHANGED_MEANWHILE)
    now = _mails(Plan(found.address))
    if now.mail_rows != found.mail_rows or _mails_as_read(now) != _mails_as_read(found):
        raise Refused(CHANGED_MEANWHILE)


def _mails_wait(cursor, lock_wait):
    """How long, in milliseconds, the erasure waits for `account_mails` and then for its rows, the log locked: a
    quarter of the server's deadlock timeout each (never more than `lock_wait`), so both together end before a session
    that began to wait behind the log's lock looks for a deadlock, and it is this command that gives up, never that
    session. Long enough for what holds the table for an instant: the database's own vacuum or analyze, the mail
    worker saying that it still has a mail."""
    cursor.execute("SELECT setting::int FROM pg_settings WHERE name = 'deadlock_timeout'")       # in milliseconds
    return max(min(cursor.fetchone()[0] // 4, int(lock_wait * 1000)), 1)


def _lock_timed_out(fault):
    """Whether a statement gave up waiting for a lock (PostgreSQL's lock_not_available, 55P03)."""
    return getattr(fault.__cause__, 'sqlstate', None) == '55P03'


def erase(address, instruction, by, lock_wait=LOCK_WAIT_SECONDS):
    """Erases `address` and returns the Plan that was carried out (empty: nothing was found, nothing was touched, no
    lock was taken and the trigger was never set aside). `instruction` is the data-protection officer's instruction (its
    reference and date), `by` who carries it out: both are written in the log's row of the erasure, and neither may
    hold the address (`refuse_words`). `lock_wait`: a positive number of seconds.

    Everything is read first, with no lock (`plan`). Then one transaction: the log is locked against writers, waiting
    at most `lock_wait` seconds for it (Refused when it cannot be had: nobody has waited behind this for longer). With
    the log held, `account_mails` is locked against writers and the rows of it to rewrite are locked, each waited for
    a moment only (`_mails_wait`; Refused, saying that it is the mails: a session that is writing a mail's row goes on
    to write the log, so waiting for it here for long would be a deadlock, and every writer of the log waits
    meanwhile). What must not have changed is read again (`_still`); the append-only trigger is set aside for the
    updates of `changes` only and set back before the erasure's own rows are appended. PostgreSQL undoes the setting
    aside with everything else when the transaction fails, and the function checks that the trigger is in force
    before it returns."""
    if isinstance(lock_wait, bool) or not isinstance(lock_wait, (int, float)) or not 0 < lock_wait < math.inf:
        raise ValueError('lock_wait must be a positive number of seconds')
    refuse_words(address, instruction, by)
    found = plan(address)
    _refuse(found)
    if found.empty:
        return found
    waiting_for = 'the log'
    try:
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("SELECT current_setting('lock_timeout')")
            before = cursor.fetchone()[0]
            cursor.execute("SELECT set_config('lock_timeout', %s, true)", [f'{max(int(lock_wait * 1000), 1)}ms'])
            cursor.execute('LOCK TABLE audit_log IN SHARE ROW EXCLUSIVE MODE')
            waiting_for = 'the mails'
            cursor.execute("SELECT set_config('lock_timeout', %s, true)", [f'{_mails_wait(cursor, lock_wait)}ms'])
            cursor.execute('LOCK TABLE account_mails IN SHARE ROW EXCLUSIVE MODE')
            list(AccountMail.objects.select_for_update().filter(
                pk__in=[mail.pk for mail, _mine, _error in found.mails]).values_list('pk'))
            waiting_for = None
            _still(found, cursor)
            for mail, mine, error in found.mails:
                values = {**({'address': ERASED_ADDRESS} if mine else {}),
                          **({'error': error} if error is not None else {})}
                AccountMail.objects.filter(pk=mail.pk).update(**values)
            if found.entries:
                cursor.execute(f'ALTER TABLE audit_log DISABLE TRIGGER {TRIGGER}')
                for entry, _labels, changes in found.entries:
                    _rewrite(cursor, entry, changes)
                cursor.execute(f'ALTER TABLE audit_log ENABLE TRIGGER {TRIGGER}')
            _say(found, instruction, by)
            if not trigger_in_force(cursor):
                raise RuntimeError(f'The activity log’s append-only trigger ({TRIGGER}) is not in force: nothing is '
                                   f'kept.')
            cursor.execute("SELECT set_config('lock_timeout', %s, true)", [before])     # a caller's transaction goes on
    except OperationalError as fault:
        if not _lock_timed_out(fault) or waiting_for is None:
            raise
        if waiting_for == 'the mails':
            raise Refused('A row of account_mails is being written by another session right now (a mail is being sent, '
                          'or what became of one is being recorded) and could not be locked in the moment this command '
                          'waits for it: nothing was changed. Run it again. (It waits for the mails for a moment only: '
                          'it holds the lock on the activity log by then, and every writer of the log waits with '
                          'it.)') from None
        raise Refused(f'The activity log is being written to and could not be locked within {lock_wait:g} second(s): '
                      f'nothing was changed. Run it again. (While this command waits for the lock, every writer of '
                      f'the log, the alarms among them, waits behind it: so it does not wait for longer.)') from None
    return found


def _rewrite(cursor, entry, changes):
    """One row of the log with its address replaced: `changes` alone is written."""
    cursor.execute('UPDATE audit_log SET changes = %s::jsonb WHERE id = %s', [json.dumps(changes), entry.pk])


def _label(user, fallback, address):
    """The name the erasure's row is under: the account's, or None when that name holds the address in any way
    (`written_holds`: a username may be an address, and the row must not hold what it says was erased)."""
    name = audit.english(user) if user is not None else fallback
    return audit.bounded(name) if name and not written_holds(name, address) else None


def _say(found, instruction, by):
    """The erasure's own row, on each account touched: that it was done, on which instruction and by whom; never the
    address. The label and what was erased are msgids, shown translated; the instruction and the name are a person's
    words and stay as typed."""
    users = get_user_model().objects.in_bulk(found.accounts)
    names = {int(entry.entity_id): entry.entity_label for entry, _labels, _changes in found.entries
             if entry.entity_id.isdigit()}
    changes = {ERASED_LABEL: [None, audit.message(WHAT)], INSTRUCTION_LABEL: [None, instruction], BY_LABEL: [None, by]}
    for pk in found.accounts:
        user = users.get(pk)
        AuditLog.objects.create(
            user=None, user_name='system', action=AuditLog.Action.UPDATE, entity_type=user_type(), entity_id=str(pk),
            entity_label=_label(user, names.get(pk), found.address) or f'account {pk}',
            changes=changes)
