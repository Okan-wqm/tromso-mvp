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
beside the name; a sentence whose brackets do not balance, or with a name that holds an address or a number, became one
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
| 8 | The address of a stranger an invitation was mis-sent to | No page changes it: it is the evidence of where a link went | The platform's database administrator, on the DPO's written instruction | See "A stranger's address" below: `account_mails` by the statement there; the log's own rows only if the owner and the DPO decide so. |

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
| the activity log, on that user's rows (read by every role with Activity log) | Created and Changed: the account's `Email` then and after (main's decision, F-050); Invited: `Sent to`; Password set: `Link sent to`, when the stranger used the link |

It is kept on purpose: it is the evidence of where a link to an account went, and the only trace when a stranger used
that link before the address was put right (the users row then says "through the link sent to …, which is not this
account's address now"). Correcting the account does not remove it, and no page does.

**On the stranger's request** (step 8 of the procedure; the DPO decides, since erasing it removes that evidence):

- `account_mails`: the platform's database administrator, on the DPO's written instruction, replaces the address (and
  the reason, where it repeats it) in the rows named, and writes the log's row of it, in one transaction:

```sql
BEGIN;
UPDATE account_mails SET address = 'erased@invalid', error = CASE WHEN error = '' THEN '' ELSE '[Erased on request, 2026-11-11]' END
WHERE id IN (...);
INSERT INTO audit_log (id, created_at, user_name, action, entity_type, entity_id, entity_label, changes, severity)
SELECT gen_random_uuid(), clock_timestamp(), 'system', 'update', 'user', id::text, left(username, 255),
       '{"Erased on request": [null, "The address of a mis-sent invitation erased on request (DPO instruction of 2026-11-11); carried out by <name>."]}'::jsonb,
       'normal'
FROM auth_user WHERE id IN (...);    -- the accounts whose mails were touched above
COMMIT;
```

- the activity log's own rows: the log is append-only (a trigger refuses UPDATE and DELETE, for the platform admin
  too), so the address in them cannot be changed through any page or by an ordinary statement. It can be replaced only
  by the database administrator with the trigger lifted for that one transaction, the way the conversion
  `core/0011` did it (`core/migrations/_private.py`: `ALTER TABLE audit_log DISABLE TRIGGER trg_audit_log_append_only`,
  the change, `ENABLE TRIGGER`), replacing the address in the `changes` of the rows named by the same placeholder and
  adding the "Erased on request" row above. **Open, for the owner and the DPO:** whether the log is ever changed for
  this, or the request is answered with the ground for keeping it (the security of the account). Nothing is built for
  it, and nothing should be until that is decided.
- backups hold it as they hold everything else (below).

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
| The address an invitation or a password link went to: the log's "Invited" rows (`Sent to`) and "Password set" rows (`Link sent to`), and the table `account_mails` (`address`, one row per mail the platform sent or tried to) | The same decision as the account's address, which it is at that moment: a link used before a mistyped address was put right is found by exactly this value, in the log and on the users row. `account_mails` is no log of the person's words: who the mail was for, the address, who asked, when it went out or why not (a mail server's reply can repeat the address). It holds no link and no token, so no column of it is masked in the database viewer, which the platform admin alone opens; the activity log, which a role can be given, never gets the mail server's words. A mistyped address of a stranger stays in both: it is not erased by correcting the account (the log is append-only; an `account_mails` row would be changed by the platform's database administrator on the DPO's written instruction, as step 6). |
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
