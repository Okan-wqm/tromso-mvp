"""Erasing, on request, the address of a stranger an invitation was mis-sent to (docs/erasure.md, step 8; the owner's
decision of 2026-11-11: yes, the activity log is changed for this).

The platform admin mistypes a new person's address; the invitation goes to whoever has that address, and the address
then stays in two places after the account's own address has been put right: the table `account_mails` (one row per
mail sent or tried: `address`, and `error` where a mail server's reply repeats it) and the activity log's rows of that
account (Created and Changed: `Email`; Invited: `Sent to`; Password set: `Link sent to`). `erase` replaces it in both,
in one transaction, and writes one new log row on each account it touched: "Erased on request", with the instruction
it was done on and who carried it out. It is the one writer that changes rows of the log after core/0011: the log is
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
- **A stranger's address only.** It refuses an address that is the address of any account now (whatever its case, the
  spaces around it, the account active or not): an account's own address is kept, with its reason, in docs/erasure.md.
  It also waits for a mail to that address that is still with the mail worker: its row is about to say what became
  of it.
- **Only that address.** A value is replaced when it is that address and nothing else, under those labels, on rows of
  user accounts; inside a mail server's reply (`account_mails.error`) the address is replaced where it stands as a
  whole address, never as a part of a longer one. Whatever else holds the text (an account's username, a record's
  name, another record's field) is listed for the operator and left as it is.
- **Nothing it writes holds the address.** The instruction and the name of who carries it out are refused when they
  hold it (they would put it back into the log, where this command would not find it again), and its own rows are
  written under the account's number when the account's username holds it.
- **Not undone, and not complete beyond the database**: backups hold the address as they hold everything else.

`plan` reads only; `erase` writes. The command `manage.py erase_stranger_address` is the only caller: no page does
this (it removes the evidence of where a link went, so the data-protection officer decides each case)."""
import json
import re
import unicodedata
from dataclasses import dataclass, field

from django.contrib.auth import get_user_model
from django.db import connection, transaction

from . import accountmail, audit
from .models import AccountMail, AuditLog

TRIGGER = 'trg_audit_log_append_only'
ERASED_ADDRESS = accountmail.ERASED_ADDRESS
ERASED = accountmail.ERASED
ERASED_LABEL = 'Erased on request'                    # the label of the erasure's own row (audit.MIGRATION_WORDS)
SAID = 'The address of a mis-sent invitation erased on request ({instruction}); carried out by {by}.'


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


def same(one, other):
    return isinstance(one, str) and _folded(one) == _folded(other)


def inside(address):
    """The pattern of `address` standing as a whole address inside a longer text (a mail server's reply), whatever
    its case: not as the tail of a longer local part (`anna@x.no` when `a@x.no` is asked for) nor the head of a
    longer domain (`a@x.no.example`). A quotation mark before it is the reply's own (`{'a@x.no': (550, ...)}`, as
    Python writes a refused recipient), not a part of the address."""
    return re.compile(r'(?<![\w.+%-])' + re.escape(address.strip()) + r'(?![\w-]|\.\w)', re.IGNORECASE)


def _without(pattern, error):
    """A mail server's reply with the address replaced, cut to the column as a reason is (the placeholder can be longer
    than the address it stands for)."""
    text = pattern.sub(ERASED_ADDRESS, error)
    return text if len(text) <= accountmail.REASON_LENGTH else text[:accountmail.REASON_LENGTH - 1] + '…'


# A run of the characters an address is usually made of, around an "@": what `holds` reads as one address in a text.
TOKEN = re.compile(r'[\w.+%-]+@[\w.-]+')


def holds(text, address):
    """Whether `text` holds `address` as a whole address, compared as addresses are compared here: in any case and
    Unicode form (`_folded`), and inside a longer text (`inside`, and every address-like run of the text by itself,
    its closing full stops aside)."""
    if not isinstance(text, str):
        return False
    return bool(inside(_folded(address)).search(_folded(text))) or any(
        same(found.group().rstrip('.'), address) for found in TOKEN.finditer(text))


def holders(address):
    """The accounts whose own address `address` is now, active or not."""
    return [user for user in get_user_model().objects.exclude(email='').order_by('pk') if same(user.email, address)]


@dataclass
class Plan:
    """What an erasure of `address` would change, and what else holds its text."""
    address: str
    mails: list = field(default_factory=list)       # [(AccountMail, address replaced?, the error as it would be or None)]
    entries: list = field(default_factory=list)     # [(AuditLog, the labels changed, its changes as they would be)]
    elsewhere: list = field(default_factory=list)   # [words]: where else the text stands, left as it is
    held_by: list = field(default_factory=list)     # the accounts whose own address it is: the erasure is refused
    waiting: list = field(default_factory=list)     # mails to it still with the mail worker: the erasure waits

    @property
    def accounts(self):
        """The ids of the accounts whose rows would change, in order."""
        found = [mail.user_id for mail, _address, _error in self.mails]
        found += [int(entry.entity_id) for entry, _labels, _changes in self.entries if entry.entity_id.isdigit()]
        return sorted(set(found))

    @property
    def empty(self):
        return not self.mails and not self.entries


def plan(address):
    """The Plan for `address`. Reads only."""
    found = Plan(address.strip(), held_by=holders(address))
    pattern, own = inside(address), labels()
    for mail in AccountMail.objects.select_related('user').order_by('pk'):
        mine = same(mail.address, address)
        error = _without(pattern, mail.error) if mail.error and pattern.search(mail.error) else None
        if mine or error is not None:
            found.mails.append((mail, mine, error))
        if mine and accountmail.state(mail) == accountmail.WAITING:
            found.waiting.append(mail)
    for entry in AuditLog.objects.filter(entity_type=user_type()).order_by('created_at', 'id'):
        changes, changed = dict(entry.changes or {}), []
        for label, pair in changes.items():
            if not isinstance(pair, list):
                continue
            if label in own and any(same(value, address) for value in pair):
                changes[label] = [ERASED if same(value, address) else value for value in pair]
                changed.append(label)
            elif any(isinstance(value, str) and pattern.search(value) for value in pair):
                found.elsewhere.append(f'activity log {entry.pk} ({entry.action} of user {entry.entity_label}): under '
                                       f'“{label}”')
        if changed:
            found.entries.append((entry, changed, changes))
    found.elsewhere += _elsewhere(address, pattern)
    return found


def _elsewhere(address, pattern):
    """Where else the text of the address stands, for the operator to see: the name a log row is under or was written
    by, a row of another kind of record, an account's username. A search of the text as stored: an address holding a
    quotation mark or a backslash is written otherwise in the log's JSON and is not found by it."""
    text, found = address.strip(), []
    for user in get_user_model().objects.filter(username__icontains=text).order_by('pk'):
        if pattern.search(user.username):
            found.append(f'the username of account {user.pk} ({user.username})')
    named = AuditLog.objects.filter(entity_label__icontains=text) | AuditLog.objects.filter(user_name__icontains=text)
    count = sum(1 for entry in named.only('entity_label', 'user_name')
                if pattern.search(entry.entity_label) or pattern.search(entry.user_name))
    if count:
        found.append(f'{count} activity-log row(s) written under or by that name (the record’s label, the user’s name)')
    others = AuditLog.objects.exclude(entity_type=user_type()).filter(changes__icontains=text).order_by('created_at', 'id')
    for entry in others.only('entity_type', 'entity_label', 'action', 'changes'):
        if pattern.search(json.dumps(entry.changes, ensure_ascii=False)):
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
        if holds(text, address):
            raise Refused(f'{what} holds the address itself. It is written into the activity log, where the address '
                          f'would then stand again and this command would not find it: give the instruction’s '
                          f'reference and date (and your name) without the address.')


def erase(address, instruction, by):
    """Erases `address` and returns the Plan that was carried out (empty: nothing was found, nothing was touched and
    the trigger was never set aside). `instruction` is the data-protection officer's instruction (its reference and
    date), `by` who carries it out: both are written in the log's row of the erasure, and neither may hold the address
    (`refuse_words`).

    One transaction. Writers of the log wait from the lock to the commit, so no row is written between the read and
    the updates; the append-only trigger is set aside after the read, for the updates of `changes` only, and set back
    before the erasure's own rows are appended. PostgreSQL undoes the setting aside with everything else when the
    transaction fails, and the function checks that the trigger is in force before it returns."""
    refuse_words(address, instruction, by)
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute('LOCK TABLE audit_log IN SHARE ROW EXCLUSIVE MODE')
        found = plan(address)
        if found.held_by:
            names = ', '.join(user.get_username() for user in found.held_by)
            raise Refused(f'{found.address} is the address of an account now ({names}): this erases a stranger’s '
                          f'address only. An account’s own address is kept (docs/erasure.md, What remains in plain '
                          f'text).')
        if found.waiting:
            raise Refused(f'A mail to {found.address} is being sent right now (account_mails '
                          f'{", ".join(str(mail.pk) for mail in found.waiting)}): its row is about to say what became '
                          f'of it. Run this again when it has.')
        if found.empty:
            return found
        for mail, mine, error in found.mails:
            values = {**({'address': ERASED_ADDRESS} if mine else {}), **({'error': error} if error is not None else {})}
            AccountMail.objects.filter(pk=mail.pk).update(**values)
        if found.entries:
            cursor.execute(f'ALTER TABLE audit_log DISABLE TRIGGER {TRIGGER}')
            for entry, _labels, changes in found.entries:
                _rewrite(cursor, entry, changes)
            cursor.execute(f'ALTER TABLE audit_log ENABLE TRIGGER {TRIGGER}')
        _say(found, instruction, by)
        if not trigger_in_force(cursor):
            raise RuntimeError(f'The activity log’s append-only trigger ({TRIGGER}) is not in force: nothing is kept.')
    return found


def _rewrite(cursor, entry, changes):
    """One row of the log with its address replaced: `changes` alone is written."""
    cursor.execute('UPDATE audit_log SET changes = %s::jsonb WHERE id = %s', [json.dumps(changes), entry.pk])


def _label(user, fallback, address):
    """The name the erasure's row is under: the account's, or None when that name holds the address (a username may be
    an address, and the row must not hold what it says was erased)."""
    name = audit.english(user) if user is not None else fallback
    return audit.bounded(name) if name and not holds(name, address) else None


def _say(found, instruction, by):
    """The erasure's own row, on each account touched: that it was done, on which instruction and by whom; never the
    address."""
    users = get_user_model().objects.in_bulk(found.accounts)
    names = {int(entry.entity_id): entry.entity_label for entry, _labels, _changes in found.entries
             if entry.entity_id.isdigit()}
    said = SAID.format(instruction=instruction, by=by)
    for pk in found.accounts:
        user = users.get(pk)
        AuditLog.objects.create(
            user=None, user_name='system', action=AuditLog.Action.UPDATE, entity_type=user_type(), entity_id=str(pk),
            entity_label=_label(user, names.get(pk), found.address) or f'account {pk}',
            changes={ERASED_LABEL: [None, said]})
