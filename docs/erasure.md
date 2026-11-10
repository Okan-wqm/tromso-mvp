# Erasing a person's contact details and free text

What is erased where when a person asks for it (GDPR art. 17; **the legal assessment is the data-protection officer's,
nothing here is verified as law**), what remains and why, and who may do it. It covers what the owner decided on
2026-11-10 (findings F-059, F-061, F-179, F-050): **a contact person's e-mail and phone, and the free text people write
on tasks.** The retention of employees' HR records (leave, punches, plans, placements) is a separate, open item:
[hr-launch-checklist.md](hr-launch-checklist.md), 4.1 and 4.2.

## Why the activity log no longer stands in the way

The activity log (`audit_log`) is append-only: a database trigger refuses every UPDATE and DELETE, for the platform admin
too, because the log is what proves who changed what. Until 2026-11-10 it also held a contact's e-mail and phone and the
text of task notes in plain text, so erasing them from the records left them in the log for good.

From migration `core/0011_private_log_values` on, the log never holds those values:

| What | Where it is kept | What the log holds |
|---|---|---|
| A contact person's e-mail and phone (a site's and a supplier's contact list) | `site_contacts`, `supplier_contacts` | The contact's name and role, and for each of the two a keyed digest: `Kari (Vet, email #1a2b3c4d, phone #5e6f7a8b, primary)` |
| A site's own contact e-mail and phone | `sites.contact_email`, `sites.contact_phone` | "Private text" (with the digest) |
| A report's contact e-mail and telephone | `regulatory_reports.contact_email`, `contact_phone` | "Private text" (with the digest) |
| A task's note | `task_notes.body` | "Private text" (with the digest): that a note was added, by whom, when |
| A task's completion note and reason for cancelling | `tasks.completion_note`, `tasks.cancel_reason` | "Private text" (with the digest) |

**The digest** (`core.audit.digest`, the one mechanism, also used for HR's leave reasons and notes) is eight hex digits of
an HMAC-SHA256 of the value under the server's `SECRET_KEY`. Equal values give equal digests, so the log still shows that
a value changed and whether two values were the same. It is not the value and cannot be turned back into it.

**The rows written before** were converted by the same migration: every plain value under those labels became its
private value; an old contact list, one composed sentence whose parts cannot be told apart reliably, became one private
value as a whole. The append-only trigger was set aside for those updates only, inside the migration's transaction, and
set back; who, when and which record were not touched. The migration prints how many values in how many rows it
converted and writes the same count into the log (record type "activity log", by `system`).

The log stays readable only with the Activity log right (`core.view_auditlog`), which the platform admin grants.

## The procedure

A request reaches the data-protection officer (DPO), who decides whether it is honoured (a legal duty to keep a record
may stand against it) and writes the instruction. Then:

| # | What | Where | Who | What happens |
|---|---|---|---|---|
| 1 | A contact person of a site or a supplier | Setup › Sites / Suppliers, the record's Contact tab: remove the row, or empty its e-mail and phone | Anyone with Edit on Sites or Suppliers | The contact list is saved as a whole: the old rows are deleted from the table (a real DELETE, not a soft delete). The log gets one row: the list before and after, by name, role and digests. |
| 2 | A site's contact e-mail and phone | The site's form, Contact tab: empty the two fields | Anyone with Edit on Sites | The columns are emptied. The log shows "Private text" changed to empty. |
| 3 | The contact of a report that is **not filed** | The draft's form, Contact person tab | Anyone with Edit on Regulatory reports | As 2. |
| 4 | A task's note, completion note or reason for cancelling | No page changes them: a note is part of the work record and is never edited there | The platform's database administrator, on the DPO's written instruction | The text is replaced in the table by the statement below. The log is not touched and needs nothing: it never held the words. |
| 5 | Backups | The backup store | Whoever runs the backups | A restore brings erased values back. The DPO's instruction is kept, and step 1 to 4 are repeated after a restore from a backup older than the erasure, until that backup has aged out. |

Step 4, in one transaction, for the rows the DPO names (the checks on both tables want words, so the text is replaced, not
emptied; a completion note may be emptied):

```sql
BEGIN;
UPDATE task_notes SET body = '[Erased on request, 2026-11-10]' WHERE id IN (...);
UPDATE tasks SET completion_note = '' WHERE id IN (...);
UPDATE tasks SET cancel_reason = '[Erased on request, 2026-11-10]' WHERE id IN (...);
COMMIT;
```

These are direct writes, so the activity log has no row for them: the DPO's instruction, with the ids and the date, is
the record. (Erasing through a page, logged like any change, is not built: it needs the owner's word on who may do it.)

## What remains, and why

- **Who did what, when** (`audit_log.user_name`, the record's label, the action): the log's purpose. A user account is
  deactivated, never deleted, so its name stays on its history.
- **A contact's name and role** in the log rows of a contact list written after 2026-11-10, a site's **Site manager** and
  a report's **Contact person** (names, logged in plain text): the log says whose contact details changed. Only the e-mail
  and phone were decided private. If the DPO requires a name out of the log, that is a new decision: nothing here removes it.
- **A user account's own e-mail and name** in the log rows of Users (plain text, F-050): an account is not a contact; it is
  changed on the Users page and the old value stays in the log. Not covered by this decision.
- **A supplier's own e-mail and phone** (`suppliers.email`, `phone`: the company's address for orders) are logged in plain
  text. Where a supplier is one person, treat them as that person's and say so to the DPO.
- **The digests.** A digest is pseudonymous, not anonymous: someone who holds both the log and the server's `SECRET_KEY`
  can test a guessed e-mail or phone number against it. Without the key a guess cannot be tested. If the DPO requires
  that link cut for good, the key is rotated: every digest written before stops being comparable with anything, every
  signed-in person is signed out and open password links stop working. That is an operator's action with the owner's
  approval, not part of an ordinary request.
- **A filed report** (`regulatory_report_snapshots`): a copy of what was told to the authority, with the contact person
  as filed, append-only by a trigger. It is kept as the law on the report requires; the DPO decides for how long.
- **The database viewer** (Administration › Database, the platform admin only) shows the tables as they are, the contact
  tables and the task notes among them, until they are erased as above.

## Checks

`core/tests_private_log.py` (the digest, the conversion, the trigger back in place, the log page),
`farm/tests/test_private_contacts.py` (contact lists and a site's contact fields through the pages),
`tasks/tests/test_pages.py` and `reports/tests/test_pages.py` (notes and a report's contact through the pages): each
asserts that the value is nowhere in the log.
