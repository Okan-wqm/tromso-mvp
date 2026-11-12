# Erasing a person's contact details and free text

What is erased where when a person asks for it (GDPR art. 17; **the legal assessment is the data-protection officer's,
nothing here is verified as law**), what remains and why, and who may do it. It covers what the owner decided on
2026-11-10 (findings F-059, F-061, F-179, F-050, and the review of the branch that built it): **a contact's e-mail and
phone, and the free text people write on tasks.** The retention of employees' HR records (leave, punches, plans,
placements) is a separate, open item: [hr-launch-checklist.md](hr-launch-checklist.md), 4.1 and 4.2.

## The activity log: pseudonymised, not erased

The activity log (`audit_log`) is append-only: a database trigger refuses every UPDATE and DELETE, for the platform admin
too, because the log is what proves who changed what. Until 2026-11-10 it held a contact's e-mail and phone and people's
free text in plain text, so erasing them from the records left them in the log for good. Now it holds a **private
value** in their place: the words "Private text" and a short keyed digest.

**Rows of the log are changed in two cases only, each by one piece of code that sets the trigger aside inside its own
transaction and sets it back:** the conversion of the rows written before (`core/0011`, below), and, since the owner's
decision of 2026-11-11, the erasure of a stranger's address on request (`manage.py erase_stranger_address`, "A
stranger's address" below). No page and no ordinary statement can.

| What is private in the log | Where the value itself is kept | What the log shows |
|---|---|---|
| A contact person's e-mail and phone (a site's and a supplier's contact list) | `site_contacts`, `supplier_contacts` | Who the contact is in plain text, then `Email: Private text`, `Phone: Private text` |
| A site's own contact e-mail and phone | `sites.contact_email`, `contact_phone` | Private text |
| A supplier's own e-mail and phone (a supplier may be one person) | `suppliers.email`, `phone` | Private text |
| A report's contact e-mail and telephone | `regulatory_reports.contact_email`, `contact_phone` | Private text |
| A task's and a recurring task's description | `tasks.description`, `task_series.description` | Private text |
| A task's note | `task_notes.body` | Private text: that a note was added, by whom, when |
| A task's completion note and reason for cancelling | `tasks.completion_note`, `cancel_reason`; after a reopening `task_notes.body` (see below) | Private text |

**The digest** (`core.audit.digest`, the one mechanism, also used for HR's leave reasons and notes) is eight hex digits
of an HMAC-SHA256 of the value under the digests' own key (`DJANGO_AUDIT_DIGEST_KEY`; the server's secret key when it
is not set). What it is and is not:

- It is **pseudonymisation, not erasure.** The value is not in the log, and it cannot be read back from the digest.
- **Whoever holds both the key and the log can recover a short value.** A phone number is one of a few tens of millions:
  trying them all against one digest took the reviewer 141 seconds on a desktop and left exactly one match. An e-mail
  from a known list is instant. Long free text cannot be recovered so, but a guessed sentence can be confirmed.
- **Without the key** the stored digests say nothing, and **no page prints a digest**: the activity log and the History
  tab of a record show "Private text", and the database viewer masks the log's `changes` column (cells, search, sort,
  filter and CSV export), so nobody tests a guess through the application (typing a value and comparing). **Who can see
  a digest:** only someone with direct access to the database or to a dump of it (the database administrator, whoever
  holds a backup). That is accepted: the same person reads the tables the values themselves are in.
- Two equal digests mean **probably the same value** (32 bits: reliable for "this field changed in this edit", not for
  "the same value" across a whole log; a false match among 10,000 different values has about a 1 % chance).
- **Cutting the link for good** is rotating the digests' key: every digest written before stops comparing with
  anything, later changes are still shown as changes, and nobody is signed out (the secret key is another key). An
  operator's action with the owner's approval, not part of an ordinary request.

**Who reads the log.** The activity log page needs the Activity log right (`core.view_auditlog`), which the platform
admin grants. A record's **History tab** (its last 20 log rows) is read by whoever may **edit** that record, without that
right: a second audience. Both show the same text, never a digest. The database viewer (the platform admin only) lists
the log's rows with `changes` masked: who, when and which record, not what changed.

**The rows written before** were converted by migration `core/0011_private_log_values`, with the trigger set aside for
those updates only, inside its transaction, and set back; who, when and which record were not touched. An old contact
list was one sentence; it was taken apart so that only the e-mail and the phone were hidden and the name, the role, the
primary flag and who was added or taken off stayed. It is read with matched brackets (a role such as "Service manager
(24 h line)" or a phone such as "(0532) 123 45 67" is read as what it is) and from the right-hand end: the e-mail is
what the contact form itself accepts as an address, the phone is digits in a phone's form. No address and no number of
five digits or more is left in plain text unless it stood in the role, left of the e-mail. Where a role and a phone
could not be told apart (a number written with words, an address typed into the role), both became one private part
beside the name. **A number typed in pieces** (review R24): with no e-mail in the contact, the details at the end that
each have a phone's form (five digits or more) are the phone, and what stands before them is the role, whose pieces
are judged **together**: when they hold five digits or more between them ("55 12, 34 56", "0532, 123, 4567") they are
not a role, and all the details become one private part beside the name. Two edges of that rule, as they are: a short
piece that stands before a piece which is itself a phone is judged without it and stays plain as the role
("Kari (0532, 1234567)" keeps "0532" beside a private phone: fewer than five digits is no number); and an innocent role
with five digits or more across its commas ("Ward 12, Building 345") goes private, the name kept, one-way. A database
converted before 2026-11-11 is not read again for either: a converted contact list is no longer a sentence, so neither
the command nor the check core.W004 can find such a row there (the development database, the only one converted
before, held none by the reviewer's scan); a sentence whose brackets do not balance, or with a name that holds an address or a number, became one
private value. Words without a number typed into the phone box ("ask reception") stay in plain text as a role. Both are
counted in the migration's output and in its own log row (record type "activity log"), which lists the entries of the
second kind. **The conversion is one-way**: nothing restores the words but a backup taken before it (see Backups).

**"The log never holds those values" holds only if** every server was stopped before the migration ran: a server still
running the code from before writes plain values behind it. `manage.py check --database default` (core.W004) counts
plain values under the private labels, and `manage.py private_log_values` converts them; the landing recipe stops the
server first.

## The procedure

A request reaches the data-protection officer (DPO), who decides whether it is honoured (a legal duty to keep a record
may stand against it) and writes the instruction. **The instruction is the record of why**: steps 1 to 3 are ordinary
edits, open to anyone with Edit on the area, and the log does not tell an erasure from a correction. Keep it where the
company keeps its data-protection records, with the date and who carried it out.

| # | What | Where | Who | What happens |
|---|---|---|---|---|
| 1 | A contact person of a site or a supplier | Setup › Sites / Suppliers, the record's Contact tab: remove the row, or empty its e-mail and phone | Anyone with Edit on Sites or Suppliers | The contact list is saved as a whole: the old rows are deleted from the table (a real DELETE; the contact rows have no soft delete). The log gets one row: the list before and after, by name and role, the rest private. |
| 2 | A site's or a supplier's own contact e-mail and phone | The record's form, Contact tab: empty the fields | Anyone with Edit on Sites or Suppliers | The columns are emptied. The log shows "Private text" changed to empty. |
| 3 | The contact of a report that is **not filed** | The draft's form, Contact person tab | Anyone with Edit on Regulatory reports | As 2. |
| 4 | A record **in the bin** (a deleted site or supplier keeps its contact rows and fields and has no edit page) | The admin: restore it, do step 1 or 2, delete it again | The platform admin | Three log rows (restored, changed, deleted). |
| 5 | A task's description | The task's (or the recurring task's) form | Anyone with Edit on Tasks | The column is changed; the log shows "Private text" changed. |
| 6 | A task's note, completion note or reason for cancelling | No page changes them: they are part of the work record | The platform's database administrator, on the DPO's written instruction | The statement below: the text is replaced, and one log row says that it was, with no words. |
| 7 | Backups | See Backups | Whoever keeps them | A restore brings erased values back: steps 1 to 6 are repeated after a restore from a dump older than the erasure. |
| 8 | The address of a stranger an invitation was mis-sent to | No page changes it: it is the evidence of where a link went. `manage.py erase_stranger_address` | The platform's database administrator, on the DPO's written instruction for that address | See "A stranger's address" below: the address is replaced by a placeholder in `account_mails` and in the activity log's rows of the account, in one transaction, and one "Erased on request" row is added on each account touched. The command checks only that no account has the address now; whether it was a stranger's is the DPO's judgement, on what the dry run shows. |

**A reopened task.** Reopening clears the completion note and the reason for cancelling on the task and keeps each as a
note by the person who wrote it (`task_notes`, `kind` `completion_note` or `cancel_reason`), so that nothing a person
wrote is lost by a reopening. Look for a person's words in `task_notes` as well as in `tasks`.

Step 6, in one transaction, for the rows the DPO names (the checks on both tables want words, so the text is replaced,
not emptied; a completion note may be emptied). The last statement writes the log's row, as every other direct write in
this system does (the shape of `core/migrations/_log.system_entry`): the task, that it was erased on request, never the
words. Its label is `Erased on request`, not `Note`: a task's `Note` is a private label, and a plain sentence under it
would be reported by the check core.W004 as a value left behind and turned into "Private text" by the command it names.

```sql
BEGIN;
UPDATE task_notes SET body = '[Erased on request, 2026-11-10]' WHERE id IN (...);
UPDATE tasks SET completion_note = '' WHERE id IN (...);
UPDATE tasks SET cancel_reason = '[Erased on request, 2026-11-10]' WHERE id IN (...);
INSERT INTO audit_log (id, created_at, user_name, action, entity_type, entity_id, entity_label, changes, severity)
SELECT gen_random_uuid(), clock_timestamp(), 'system', 'update', 'task', id::text, left(title, 255),
       '{"Erased on request": [null, "Free text erased on request (DPO instruction of 2026-11-10); carried out by <name>."]}'::jsonb,
       'normal'
FROM tasks WHERE id IN (...);        -- every task touched above
COMMIT;
```

(Erasing a note through a page is not built: it needs the owner's word on who may do it.)

## A stranger's address: an invitation sent to a mistyped address

**For the owner, plainly.** When the platform admin mistypes a new person's address, the invitation goes to whoever
has that address: a stranger, who never agreed to anything. Their address then stays in the system after the admin
has put the account's address right:

| Where | What is kept |
|---|---|
| `account_mails` (the platform admin reads it in the database viewer and on the users tab) | one row per invitation that went, or was tried, to that address: `address`, and `error` when a mail server's reply repeated it |
| the activity log, on that user's rows (read by every role with Activity log) | Created and Changed: the account's `Email` then and after (main's decision, F-050); Invited: `Sent to` (the admin's row, and the platform's own "Not sent" row when the mail did not go out); Password set: `Link sent to`, when the stranger used the link |

It is kept on purpose: it is the evidence of where a link to an account went, and the only trace when a stranger used
that link before the address was put right. Correcting the account does not remove it, and no page does.

**What the users tab shows of it** (Company › Administration › Users, the platform admin only), on the row of that
account:

| When | Before an erasure | After it |
|---|---|---|
| The stranger set a password through the link, and the account's address was put right afterwards | "Password set *when* through the link sent to *the address*, which is not this account's address now." The address is read from the activity log's "Password set" row (`Link sent to`), not from `account_mails`. | "Password set *when* through the link sent to an address that was erased on request, which is not this account's address now." |
| The last invitation went to that address and the account's address was put right, with no invitation since | "Invitation sent *when* to *the address*; the address has changed since, so its link no longer works." Read from `account_mails` (the last invitation's row). | "Invitation sent *when* to an address that was erased on request; the address has changed since, so its link no longer works." |
| The last invitation to that address did not go out | "Invitation not sent", then "*when*, to *the address*: *the reason*", the reason being the mail server's words, which can repeat the address. Read from `account_mails`. | "*when*, to an address that was erased on request: *the reason*", with `erased@invalid` where the reply named the address. |

The account's History tab and the activity log show the same rows: before, the address under `Email`, `Sent to` and
`Link sent to`; after, "Erased on request" in its place (in the reader's language). The rows themselves stay: who
invited whom and when, that a link was used, that the address was changed.

**On the stranger's request** (step 8 of the procedure). **The owner decided on 2026-11-11 that the address is erased
from the activity log too.** The data-protection officer still decides each case, because the erasure removes the
evidence of where a link went: after it, nobody can tell from the system which address a password link reached. The
platform's database administrator carries the decision out with the command, never with a statement written by hand:

```
python manage.py erase_stranger_address stranger@example.com
python manage.py erase_stranger_address stranger@example.com --apply \
    --instruction "DPO instruction of 2026-11-11, ref. DP-17" --carried-out-by "Kari Nordmann"
```

- **What the command checks, and what it cannot.** It refuses an address that is the address of any account **now**
  (whatever its case or the spaces around it, the account active or not), and it **refuses** while a mail to that
  address is still being sent: it does not wait for it; run it again when the mail's row says what became of it.
  **That is all it checks.** It cannot tell a stranger's address from an address that was a person's
  own for a year, or from one an intruder put on an account and took off again (the evidence the decision F-050
  keeps): to the code all three are "an address an account once had". Telling them apart is the DPO's judgement.
- **What the dry run shows for that judgement.** Without `--apply` nothing is changed. It lists every `account_mails`
  row and every activity-log row that would change, with the labels (and the value as it is stored, when that is not
  how it was typed: another case, another Unicode form); then, for each account touched, what the log says: from when
  to when the address was the account's own (its Created and Changed `Email` rows, and by whom), whether it
  **replaced an earlier address** of the account (a Changed row with a former `Email`), every invitation sent or
  tried to it, whether a password was set through a link sent to it, when and by which account, and how many other
  log rows the account wrote itself meanwhile (counted by the row's key of who wrote it, so an account renamed since
  loses none; a row without that key counts under any name the account's rows carry). It adds a **warning** when
  this does not look like a stranger's address:
  - **the address replaced an earlier address of the account and a password was set through a link sent to it**:
    this is how an account is taken over through a changed address, and the warning comes whatever the durations (a
    takeover needs minutes: the address changed, the link used, the old address put back);
  - the address was the account's own for a day or more; the log has no row that ends it; the account was used
    while it had it; more than one password was set through it.

  The warning informs; with `--apply` the command obeys the DPO's decision all the same.
- **The instruction and the name are written into the log, so they must not hold the address.** `--instruction` takes
  the instruction's reference and date, `--carried-out-by` the operator's name. The command refuses either when the
  address stands **anywhere** in it, in any case or Unicode form, as a part of a longer word or of a longer address
  too (`stranger@example.com.Confirmed`, `stranger@example.com-DP17`, `ref.stranger@example.com`, and
  `xstranger@example.com` as well): it would stand in the log again, in a row this command would not find. This
  refusal refuses rather once too often; reword the instruction. For the same reason its own row is written under
  `account <id>` when the account's username holds the address in any such way.
- **The Turkish capital İ and the dotless ı** (decided with the second review, 12.11.2026). An address is compared
  as the platform compares addresses everywhere: case folded, in one Unicode form. By that comparison
  `İNFO@EXAMPLE.COM` and `info@example.com` are **two addresses** (the capital İ is not the capital of i, and ı is a
  letter of its own), and what is replaced is decided by that comparison alone: asked for `info@example.com`, the
  command does not erase a row that holds `İNFO@example.com`, because it cannot know that they are one mailbox.
  The same holds inside a mail server's reply: of `550 <İNFO@example.com> and <info@example.com>` only the second is
  replaced, and the row is named for the first. (The pattern that finds an address inside a longer text ignores case,
  and Python reads İ and ı as i there; what it finds is therefore compared as addresses are before anything is
  replaced.)
  Nothing passes in silence, though. The dry run (and the run) **names** every `account_mails` row and every log row of
  a user account that holds the address only when İ and ı are read as i, with the value as stored, under "NOT
  changed, and to be looked at": when it is the same address, run the command again with the address written as it
  is stored. And the two refusals read the letters as one, since refusing once too often costs nothing there: an
  instruction or a name that holds the address read so is refused, and so is an address that an account has now when
  read so (it names the account and its address as stored). Not covered by the naming: other kinds of record, a
  username, the names on old log rows (the list "The text also stands here" searches the text as typed).
- **What it changes, in one transaction** (`core/erasure.py`):
  - `account_mails.address` of the rows of that address becomes `erased@invalid`, and where a mail server's reply in
    `error` names the address (in any row, in any case or Unicode form, as a whole address), that address inside it
    becomes `erased@invalid`; the rest of the reply stays;
  - in the activity log, on the rows of user accounts, a value that is that address under `Email`, `Sent to` or
    `Link sent to` becomes the value "Erased on request". Only `changes` is written: who, when, which record and
    every other value stay;
  - one new row on each account touched, by `system`: "Erased on request: The address of a mis-sent invitation", with
    the instruction and who carried it out under labels of their own (the labels and that sentence are shown in the
    reader's language; the instruction and the name are as typed). Never the address.
- **The log's writers wait for a short moment, the alarms among them.** Everything is read before any lock is taken.
  The command then locks the log against writers, waiting for that lock at most `--lock-wait` seconds (5; a positive
  number, anything else is refused): when the log is being written and the lock cannot be had in that time, the
  command gives up, says so and has changed nothing (a session that waits for this lock makes every later writer
  queue behind it, so the wait is bounded). **Holding the log, it waits for nothing more**: it locks `account_mails`
  against writers and the mail rows it will rewrite at once, or gives up saying that a row of `account_mails` is
  being written (the mail worker writes a mail's row and then the log; waiting for it with the log locked would be a
  deadlock, with every writer of the log waiting meanwhile). Under the locks it reads again what must not have
  changed: that no account has the address now, that the log rows to rewrite are as they were read, that no row of a
  user account was added, and **every mail again**: the same rows hold the address, with the same values, and no
  other row has come to hold it (a mail server's reply recorded meanwhile, a new mail). Otherwise it stops, has
  changed nothing and asks to be run again. Then it writes. The append-only trigger is set aside for the updates of `changes` only and is
  back in force before the transaction ends; when anything fails, nothing is kept and the trigger is in force
  (PostgreSQL undoes the setting aside with the rest, and the command checks it before it commits).
- **A placeholder, not a digest.** Nothing of the address is kept: no keyed digest, unlike the private values of
  `core/0011`. Two erased addresses cannot be told apart or compared with anything afterwards.
- **Only that address, only there, and what is left.** An address that merely contains it (`xstranger@example.com`) is
  another person's and is not touched. The command names every other place it finds the text and leaves it:
  - on a user's row, under another label or in another shape of value than a plain pair (a list inside, an address
    with a name around it): left, and no step of this procedure changes it; if it must go, it is a new decision;
  - in a row of another kind of record: erased, if at all, by the step that kind belongs to (steps 1 to 6);
  - **an account's username, and the name a log row is under (`entity_label`) or was written by (`user_name`):
    nothing in this procedure covers them.** A username that is an address can be changed on the users tab for the
    future; the log's old rows keep the old name, and no tool changes them. The command says how many such rows there
    are.
  What the command cannot see, and so does not list: the address inside a mail server's reply in another form: cut
  off by the column's 500 characters, rewritten by a mailing system (`name=domain@bounce.example`), or in another
  Unicode form when the part before the `@` holds a character other than letters, digits and `. + % -`. Read the
  `error` of the rows it lists.
- **Run again** it finds nothing and touches nothing. An address nobody has seen is reported as not found, and neither
  the lock nor the trigger is touched for it.
- **Backups hold it** as they hold everything else (below): a restore from a dump older than the erasure brings the
  address back, and the erasure is repeated after it.

## Backups

A dump taken before an erasure holds the erased values, and the dump taken before `core/0011` runs holds the whole log
in plain text: it is the only way back over that one-way conversion and, at the same time, where the erased words live
on. Today the development dumps are written by hand into the folder `CLAUDE.md` names (Database backups: a folder that
is synchronised to a cloud drive), and nothing deletes them. **Open, for the owner and the DPO:** how long a dump is
kept and who deletes it. Until that is set, name the dump taken before `core/0011` in the DPO's records, and delete it
once the landing is confirmed and no way back is wanted.

## What remains in plain text, and why

Decided with the conversion (the owner, 2026-11-10), so that the log still says what happened to whom:

| Kept plain | Why |
|---|---|
| Who did what, when (`user_name`, the record's label, the action) | The log's purpose. A user account is deactivated, never deleted, so its name stays on its history. |
| A contact's name, role and primary flag | The row says whose contact details changed and who the contact was. A remaining item for the DPO: if a name must leave the log, that is a new decision; nothing here removes it. |
| A site's Site manager, a report's Contact person | Names: who ran the site when; the filed copy of a report keeps its contact by law. |
| A supplier's name, organisation number and address | A company's data, public register data also for a sole trader; the name is the record's label. |
| A user account's e-mail address | Kept, with the reason (this closes F-050): a changed account address is how an account is taken over by a password link, and the new address is the evidence. The account is never deleted, so `auth_user` keeps the address in any case; hiding it in the log would erase nothing. |
| A user account's name, username and roles | `user_name` is the log. |
| The address an invitation or a password link went to: the log's "Invited" rows (`Sent to`) and "Password set" rows (`Link sent to`), and the table `account_mails` (`address`, one row per mail the platform sent or tried to) | The same decision as the account's address, which it is at that moment: a link used before a mistyped address was put right is found by exactly this value, in the log and on the users row. `account_mails` is no log of the person's words: who the mail was for, the address, who asked, when it went out or why not (a mail server's reply can repeat the address). It holds no link and no token, so no column of it is masked in the database viewer, which the platform admin alone opens; the activity log, which a role can be given, never gets the mail server's words. A mistyped address of a stranger stays in both until it is asked for: correcting the account does not erase it, and **on the stranger's request it is erased from both** (the owner, 2026-11-11; step 8, `manage.py erase_stranger_address`, on the DPO's instruction). The command erases any address no account has now; that it is a stranger's and not a person's own former address is the DPO's judgement. |
| A task's title and checklist items | The title is the record's label in every row of the task; checklist items are short work steps. |

Also outside this procedure: **a filed report** (`regulatory_report_snapshots`), a copy of what was told to the
authority with the contact as filed, append-only by a trigger and kept as the law on the report requires (the DPO
decides for how long); and the **database viewer**, which shows the tables as they are until they are erased as above.

## Checks

`core/tests_private_log.py` (the digest and its key, the conversion shape by shape, the dry run, the lock, the leftover
check, the trigger back in place, no way back), `farm/tests/test_private_contacts.py` (contact lists, a site's and a
supplier's own fields, no digest on the History tab or the log page), `tasks/tests/test_private_text.py`,
`tasks/tests/test_reopen_keeps.py`, `tasks/tests/test_pages.py` and `reports/tests/test_pages.py`: each asserts that
the value is nowhere in the log. `core/tests_account_mail.py` asserts the other side for the account e-mails: none of their
log labels is a private one, the address is in the log and in `account_mails`, and no link or token is in either.
`core/tests_erasure.py` holds the erasure of a stranger's address: the rows as the pages write them, the dry run, every
row and label changed and nothing else (other addresses, an address that contains it, other users' rows, other labels,
other kinds of record, a contact list, other shapes of value), the refusals (an instruction or a name that holds the
address in any way among them, the Turkish capitals), what the dry run says is checked and shows of each account (the
takeover pattern, the count that survives a rename), a second run, the mails read again under the locks and a mail
being written said to be a mail and not waited for, the bounded and positive wait for the
lock and the read before it, the trigger with real commits and a second session (a commit, a rollback, a fault and an
interrupt while it is set aside, a lost connection, a caller's transaction, autocommit off), and the users tab, the log
and the History tab in three languages on the erased rows.
