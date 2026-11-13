# wip/fix-security: review notes

Branch from main b24de24, main 6bf9a78 merged in at the end. Every behaviour has a `Test:` commit (seen failing for the
stated reason) before its fix commit. Findings are the verified rows of `audit-verify/result*.md`, re-checked against the
code before changing anything.

## Fixed

| Finding | Root cause | Fix | Tests |
|---|---|---|---|
| F-005 stored XSS through help text | `templates/registration/_field.html` printed `field.help_text|safe`; forms write names into help text (tasks/forms.py deleted place, farm/forms/equipment.py deleted systems). Django's own layouts (`{{ form }}`, as_p/as_table/as_ul/as_field_group) print it `|safe` too | Help text is escaped; `templates/django/forms/field.html` draws every Django field with the project template, p/table/ul fall back to div, so no layout prints it raw. Markup built with `format_html` is kept | `core.tests_escaping` (all layouts with hostile text, a scan that fails on any `|safe`/`autoescape off` in a template, an allow-list of the 4 `mark_safe` builders each with a hostile-text test, citation escaping) |
| F-005 CSP | No Content-Security-Policy | Django 6.1's `ContentSecurityPolicyMiddleware`, `SECURE_CSP` in `config/settings.py`: default/script/style/font/connect `'self'`, script nonce (the import map carries it, `core/templatetags/assets.py`), img `'self' data:`, object/base `'none'`, form-action `'self'`, frame-ancestors `'none'`. Inline styles moved: a monitoring widget's cell is classes (`gx- gy- gw- gh-`, `static/css/card-grid.css` generated from the catalogue by `manage.py card_grid_css`, `--check`; `catalogue.ROWS` = 40 widgets x tallest widget, validator and the TS designer both call a widget below it out of bounds); a capacity bar is an SVG rect (`templates/farm/_capacity_bar.html`) | `core.tests_csp` (header on every response; import-map nonce; every no-argument route opened as superuser, page and dialog, parsed for inline script/style/style attributes/handlers/javascript:/foreign loads; template scan; font), `monitoring.tests.test_render.GridStyleSheetTests`, `frontend/grid/layout.test.ts` (rows bound), `core.tests_assets` |
| F-163 Google Fonts | Both base templates loaded the font from fonts.googleapis.com | Bricolage Grotesque v9 variable woff2 (latin, latin-ext) in `static/fonts`, `@font-face` in base.css, OFL.txt beside them, `THIRD_PARTY.md` "Shipped to the browser" names font, version, licence, copyright | `core.tests_csp.FontTests`, the template scan (no foreign load) |
| F-169 / F-220 route sweep | No test that every route needs a permission | `core/tests_routes.py`: walks every route (admin apart), anonymous -> login everywhere but a named PUBLIC list, a signed-in person with no role -> 403 (404 for a record) everywhere but a named SIGNED_IN list with reasons (home, production_home, sensors:home, password change). Found one: `hr:roster_plan` answered 400 before asking for a right; now `services.can_plan` first | `core.tests_routes`, `hr.tests.test_roster.RosterUrlTests.test_the_batch_plan_view` (403) |
| F-046 preset widened on save | `core.access.implied` added Read for every action, Crew/All production/Everyone too; the Production manager preset holds All production without the Team list | One rule: Create/Edit/Delete include Read (`access.INCLUDES_READ`); Crew/All production/Everyone widen rows only and include nothing; the matrix widget's `data-requires` follows the same constant | `hr.tests.test_roles.MatrixRoundTripTests` (each preset saved unchanged/renamed through the role form keeps exactly its rights; presets closed under the rule), `hr.tests.test_production_permissions` (columns imply nothing; matrix ticks Read only with C/E/D), `core.tests_scope`, `core.tests.RoleTests` |
| F-230 lead moves people anywhere / edits own row | `services._allowed` checked the person, not the target department; own row is in one's team | `scope.managed_departments` (single source for `managed` and the new `placeable`/`can_manage`); `move` refuses a department the user does not manage; `own_record` (renamed from `self_plan`, same rule as own attendance/plan) refuses own placement/title/last day without Everyone; `EmployeeResource.allowed` 403s the own edit page, the list links own row to the read page; the department chooser offers only placeable departments | `hr.tests.test_own_record` (10 tests: other manager's/office dept refused at service and form, title inside own dept OK, All production between production depts only, Everyone anywhere, own move/last day refused, own edit page 403, list link, chooser) |
| F-096 records outside employment | Only leads were bounded (via placements); Everyone holders, own clock-in and own leave were not | `hr.services.check_employed(employee, first, last)` called by `plan_shifts` (not for clearing), `clock_in`, `enter_presence`, the attendance form and the leave form | `hr.tests.test_employment_bounds` |
| F-097 started approved leave cannot be corrected | No path after the first day | `can_correct` (decider, not own) ; `shorten_leave` (new last day in [first, last-1], logged: `last_day` added to the leave audit fields); `can_cancel` lets a decider cancel a started approved leave; route `leaverequest_shorten` (+ production mount), field on the request page | `hr.tests.test_leave_correction` (6), `hr.tests.test_scope` route list |
| Turkish "Issue" = "Sayı" | One msgid for the stock operation and the journal issue | `pgettext_lazy('stock operation', 'Issue')` on `OperationKind.ISSUE`, used by the storage page actions and the departure dialog; TR Çıkış, NB Uttak; journal issue keeps Sayı/Hefte | `inventory.tests.test_words` |
| F-042 form border contrast | Controls' edge drawn in `--sage` (1.68 on white, 1.47 on mist) | `--control: #77816B` (4.1 / 3.6) for all 11 control edges; sage stays decorative | `core.tests_contrast` (WCAG computed from the tokens; no control edge in sage) |
| F-045 / F-222 stale/gone not announced | The banner is CSS `::before` content; the announcer listened only to card merges | `announce.ts` observes the grid's `data-poll-state` and says the banner's own text assertively when it becomes stale or gone (`connectionSentence`) | `frontend/announce.test.ts` |

EN/TR/NB: new strings translated, `update_catalogs` leaves no diff. README sections: "Security in the pages" (new), Roles and users / Row scope (matrix rule), Team list (moves, own record), Leave requests (correction, employment bound), Monitoring (card grid classes, rows bound), Browser code (announcer). Data map regenerated.

## Not fixed here, and why

- F-095 forgotten clock-out (board says "not in", clock-in refused): needs a product rule for how old an open punch may be
  before it counts as forgotten and who closes it (the lead's correction already exists through the attendance form).
  Owner decision; not guessed.
- F-203 production manager preset lacks shift clear and attendance entry: the preset is a starting point an admin extends
  in the matrix; widening a role preset is an owner decision (it touches F-095 too).
- F-229 Create column for non-Everyone roles (form shown, save 403): documented, tested behaviour; UX only. Gate the create
  view early in a later pass.
- F-168 / F-173 experiment and report pages show farm figures without the farm areas' rights: plausibly by design (a
  regulatory filer needs the figures); needs the owner's word, then one line in the matrix docs or a check.
- F-059 / F-061 / F-179 / F-050 personal data in the append-only audit log (contact e-mail/phone, task notes): the log has
  no redaction path; GDPR erasure needs an owner decision on what the log may hold (the `private=` digest exists and could
  be applied to contacts and notes). Wider than this branch.
- F-098 `rest_rule` label, F-100 backdated leave bound, F-180 / F-204 leave quota without lock, F-155 no confirmation on
  leave cancel / member changes, F-156 Leave types page orphaned, F-158 off-canvas rail focusable, F-159 roster info only in
  `title`, F-160 Turkish `.lower()` (cosmetic dotted i), F-161 / F-162 / F-226 CSS hover/hidden/print (layout, likely in
  wip/bugs-nov5), F-224 void dialog wording, F-225 required marker, F-041 delete text, F-149 "undefined removed" in the
  designer (monitoring's), F-128 CSRF regression test, F-035 role edit lock, F-072 seeding without audit, F-210 assistant
  write path (not built): open, lower severity; not reached in this pass.
- Browser check: the dev server on the worktree could not be reached from the host and the Chrome extension did not
  answer, so CSP was verified by the crawl test (every no-argument page and dialog, parsed against the policy) and the
  template scan, not in a live browser. Pages that only show with records (a record's page) are covered by the template
  scan, not rendered. Worth one look in a browser before landing: the monitoring wall, the designer preview, a knowledge
  PDF opened inline (it now carries the policy too), the Django admin.
- `element.style` set from TypeScript (windows.ts, designer.ts) is CSSOM and allowed by the policy; no `setAttribute('style')`
  exists.

## Go-live (deploy-only hardening, not this branch)

Settings fail-open (F-001/040/137/171/241: SECRET_KEY, DEBUG, cookie flags); DB port 0.0.0.0 and default password
(F-129/033); backups, TimescaleDB restore runbook and restore test (F-023/182/231); login rate limit and auth events logged
(F-021/048/070, F-031); LOGGING (F-043); CI (F-028/056/126/145/185/223); production app server (F-132); upload size/time
caps (F-053, F-015); app DB role not owner, audit TRUNCATE (F-069/076/078); e-mail backend (F-014/233); DB timeouts
(F-170). A CSP `report-uri` endpoint could be added at go-live to see violations in the field.

## Verification

- Full Docker suite after merging main 6bf9a78 (balik-testrunner, test_fixsec, no --parallel): 2808 tests, 2 failures, both
  `monitoring.tests.test_pages` asserting "no `<svg>` in a card but icons": the capacity bar is now an SVG. Adjusted to count
  it beside the icons (commit 68256fc) and re-run on a fresh DB: 19/19 OK.
- `makemigrations --check`: no changes (no migration on this branch). `data_map --check`: regenerated and committed.
  `card_grid_css --check`: up to date. `compile_catalogs` OK; `update_catalogs` leaves no diff (EN/TR/NB complete).
- `npx tsc --noEmit` OK; `npm test` 42 pass, 0 fail.
- Main has since moved to 912c55d; not merged here (the full suite was run against 6bf9a78).

## Cross-review fixes (REVIEW-CROSS-security.md, APPROVE WITH FIXES)

| Item | What was done | Commits (Test first) |
|---|---|---|
| 3 announcer twice | `git revert` of 5d93141 and fa4a76f (code, test, README line): wip/fix-monitoring's superset is the only one. F-045/F-222 are that branch's | 508c6a7, 608c65e |
| 4 shorten-leave date box | **Waiting**: after wip/bugs-nov5 is on main, merge main, switch the field to the shared day input and `core.dates.read_day`, max = the day before the last day | – |
| 5 roles saved with the widened right | `hr/0010_restore_preset_rights` puts Production manager and Production worker back to exactly their rights (lists frozen in the migration, a missing preset is not made); `core.W003` (`check --database default`) lists any role holding Read and a widening column but no Create/Edit/Delete on an area; README deploy note | e4755a5 (Test: `hr.tests.test_preset_restore`), 63251f5 |
| 6 correction window | `hr.services.correction_window_days()` (31; the platform owner's correction-window setting will be read there), `past_correction`, `can_correct`: a decider shortens or cancels a started leave only within the window after its last day; older ones refused with the reason (ValidationError, not 403); TR/NB | 2d45702 (Test: `CorrectionWindowTests`), c4addc5 |
| 7 employment rule under lock + both directions + DB | `lock_employed` (row locked, then `check_employed`) in the leave, attendance and plan tabs' `after_save`, in `enter_presence` and when approving; `core.crud` now puts a ValidationError from `after_save` on the form and rolls back (it was a 500); `employment_conflicts` refuses a first/last day that would leave plans, held leave or punches outside (person form, `leave_company`; later plans and later pending leave still go with the last day); `hr/0011_employment_bounds`: constraint triggers deferred to commit on plans, leave, punches and the person's dates (a punch on its UTC day with one day of slack). main's `trigger_refusal` (merged) shows a trigger refusal on the form. Existing tests adjusted: a straddling approved leave now blocks leaving (new test), `check_hr`'s legacy-data test cleans up before Django reads deferred constraints at test end | b51184f, 090c2ac..: `hr.tests.test_employment_bounds` (`EmploymentChangesTests`, `CheckedUnderTheLockTests`); ffae113 |
| 8 route sweep | record routes must answer 403 for a no-role person; 404 only for `NOT_A_PAGE` (hr:punch, hr:production_punch: the argument is in/out, both ask the right in the service) | a797b66 |
| 9 tests that did not prove the rule | `test_the_attendance_form_refuses_a_day_before_the_person_joined`, `test_the_leave_form_refuses_days_before_the_person_joined`: seen saving (302) with `check_employed` taken out of both forms | 090c2ac |
| nit | `hr/services.py` `_allowed` line continuation | in ffae113 |

Migrations: hr `0010_restore_preset_rights`, `0011_employment_bounds` depend on hr 0008. wip/fix-integrity adds hr `0009_entry_keys`: whichever lands second re-points its first migration's dependency to the other's last one (no merge migration).

Main 912c55d merged (177eb99): one conflict in `core/crud.py` (main's IntegrityError/trigger_refusal handling kept beside this branch's ValidationError handling), data map regenerated.

Verification after the cross-review fixes (HEAD 177eb99, main 912c55d merged): full Docker suite on a fresh DB
(test_fixsec3, no --parallel: the parallel command is not on main): **2883 tests, OK (3 skipped)**.
`makemigrations --check` no changes; `data_map --check` up to date; `card_grid_css --check` up to date; catalogs current
(EN/TR/NB); `npx tsc --noEmit` OK; `npm test` 41 pass, 0 fail (the reverted announcer test is gone).
Open: item 4 (waits for wip/bugs-nov5 on main); the live-browser CSP look (monitoring wall, designer preview, inline
knowledge PDF, admin).

## Landing (main d1f5315: health-reports, bugs-nov5, integrity merged in)

- Merge conflicts resolved: `core/crud.py` takes main's edit flow (`Resource.edited`, 422 with the question, `Crossed`,
  `trigger_refusal`); main's create-view ValidationError branch now also takes a plain ValidationError from `after_save`
  (HR's employment bound under the lock). `hr/services.py`: the employment check kept beside F-024's clearing of filled
  cells only; `enter_presence` reads the day with main's `read.local_day` (`punch_day` delegates to it). Catalogs keep both
  sides; the data map regenerated.
- Item 4 done: the leave's new last day is the shared day box (`{% day_input %}`, `core.widgets.DayInput`), offered at
  the day before the last day, read by `core.dates.read_day` (an unreadable text is said back, nothing changes); the
  date-box scan and the one-parser AST guard pass (test a3f93c7, fix 2805538).
- Migrations: hr `0010_restore_preset_rights` now depends on main's hr `0009_entry_keys`; `0011_employment_bounds`
  follows it; one hr leaf. `makemigrations --check`: no changes.
- Lock order (integrity's LOCK ORDER, deepest first): HR now takes the person first, then the person's records, in every
  path (`lock_person`, FOR NO KEY UPDATE so an insert's key-share lock on the person does not deadlock with it;
  `PersonFirst.edited` for the plan, punch and leave tabs; `_lock` for approve/cancel/shorten). Test 1cb2b38, fix c3374eb.
  CrossedWritesMiddleware still answers a cycle no write foresees.
- Scans: `core/tests_escaping._sources` leaves out `docs/` (design previews, reports) and `frontend/` (browser-test fixture
  pages), which are never served.

## Owner questions still open

- F-095 forgotten clock-out: an open punch older than the board's window shows "not in" and refuses clock-in. Default:
  a punch open longer than 16 h counts as forgotten; the person is told to ask their lead, who closes it in Attendance.
- F-203 production manager preset: it cannot clear a shift cell or correct attendance. Default: add `delete_shiftassignment`,
  `add_attendancerecord` and `change_attendancerecord` to the preset (the restore migration and `hr/roles.py` then carry them).
- F-168 / F-173 experiment and report pages show farm figures to people without the farm areas' Read. Default: keep it
  (a trial's own tanks and a regulatory filing need the figures) and state it in the role matrix's help.
- F-059 / F-061 / F-179 / F-050 personal data in the append-only activity log (contact e-mail and phone, task notes).
  Default: log these fields as private (the existing keyed digest), keep the log's audience to `core.view_auditlog`, and
  write an erasure procedure that the log no longer needs.

## Design system merged (main 2f796ed, then bd6416d)

Main's design wins on look, this branch's CSP on mechanism. The fonts are main's (`static/fonts`, `fonts.css`, one
THIRD_PARTY entry each); this branch's duplicate `OFL.txt` and `@font-face` in base.css are gone. The units table keeps
main's `ui-gauge` markup with its track drawn as an SVG (`svg.ui-gauge-track`, the fill a rectangle's width, `fill:` rules
in ui.css); the capacity bar's rectangle is `--primary`, `--crit` when over; the card keeps the grid classes. No served
template holds a style attribute or a `<style>` block (docs/ previews and frontend/test fixtures are not served and are
left out of the scans). The contrast test reads every theme's `--line-control` in tokens.css (3.7:1 or more against page
and sheet). The route sweep names main's theme switch (a cookie) among the public pages.

Full suite on the merge with bd6416d (`scripts/test.sh`, archive copy): 3152 tests, 6 failures, all
`monitoring.tests.test_golden` "titles that are gone" (stale values' titles); main bd6416d alone fails the same 6 at the
same time, so they come from main, not this branch.

## Owner decisions, 2026-11-10 ("go with your recommendations"; branch wip/owner-decisions)

The four questions above are decided and built, each with its `Test:` commit first.

| Finding | Decision | What was built |
|---|---|---|
| F-095 | A clock-in open longer than a limit is a forgotten clock-out; the lead closes it | `SchedulingSettings.forgotten_after_hours` (16, HR edits it; hr/0013), one rule `hr.rules.forgotten`: its own state on the board, kept in the emergency count and said apart, the person told in words and neither clocked in nor out, closed on the Attendance page with the real time and a reason (README › Today & attendance). `hr.tests.test_forgotten` |
| F-203 | The Production manager preset clears a planned day and enters and corrects attendance | `hr/roles.py`; `hr/0012_production_manager_rights` gives an existing role the three rights, logged. 0010's restore is left as it was made: with 0012 it is the preset today, and F-046's test stays green. `hr.tests.test_manager_rights`, `test_roles`, `test_preset_restore` |
| F-168 / F-173 | Kept; said in the role matrix | `core.access.Area.note`, printed under Experiments and Regulatory reports in EN/NB/TR. `core.tests_matrix_notes` |
| F-059 / F-061 / F-179 / F-050 | Contact e-mail and phone and task free text are private in the log; the activity log page stays `core.view_auditlog` (a record's History tab is read by its editors: no digest is printed on either) | `core.audit.private` / `digest` (the existing mechanism, named); contacts, a site's, a supplier's and a report's contact fields, task free text; `core/0011_private_log_values` converts the old rows; [docs/erasure.md](../erasure.md). `core.tests_private_log`, `farm.tests.test_private_contacts`, `tasks.tests.test_pages`, `reports.tests.test_pages` |

## Review of the branch (independent, 2026-11-10: 1 blocker, 5 major, 8 minor, 4 notes), fixed on it

| Finding | What was wrong | Fix |
|---|---|---|
| R1 blocker | core/0011 made each old contact-list sentence one private value: names, roles, primary and who was added or removed were lost, one-way | The sentence is taken apart (`core/migrations/_private.py`); only e-mail and phone become private; a role and a phone that cannot be told apart become one private part, an unparseable sentence one private value, counted and named by id; `manage.py private_log_values --dry-run`; going back refused once a row was converted |
| R2 | A contact's digest was printed on the History tab to anyone with Edit, who could save a guess and compare | A contact list is logged as parts with private values; `AuditLog.shown_changes` never prints a digest |
| R3 | The digests took whatever key the migrating process had, the repository's fallback included | `AUDIT_DIGEST_KEY` (its own key); the conversion refuses a `django-insecure-` key when DEBUG is off; the docs say pseudonymisation, "probably the same", recoverable with the key |
| R4 | A server still running old code wrote plain values behind the conversion, unseen | The conversion locks the table before it reads; check core.W004; the command converts leftovers; CLAUDE.md stops the server before `migrate` |
| R5 | Reopening a task cleared the completion note and the reason, which then existed nowhere | `tasks.services.reopen` keeps each as a note by its writer (`TaskNote.kind`, tasks/0003) |
| R6 | A forgotten stretch could be closed with a time ahead | `hr.services.check_times`: nothing later than now, on the form and in the service |
| R7 | Fields of the same kind left plain | Private too: supplier e-mail and phone, a task's and a recurring task's description. Plain by decision, with reasons in docs/erasure.md (this closes F-050: the account's address is kept) |
| R8 | The limit was held against the shift, not the shift and the punch window | Both forms add `punch_window_minutes` |
| R9 | A person who moved: the new lead got a dead link | `hr.scope.stretches`: an open stretch is reached by whoever reaches the person today as well |
| R10 | The conversion's log row showed in English | Its words marked (`core.audit.MIGRATION_WORDS`) and translated |
| R11 | A deliberate 2 for a cleaner species was lost | The create box is empty and takes the offer of the kind; farm/0038 leaves and reports a 2 that came with the species' creation |
| R12 | Two Turkish strings | Corrected |
| R13 | core.W003 listed Read beside Crew | `core.access.OWN_PAGE`; the check skips it |
| R14 | Two writers of a migration's log row | alarms' migrations call `core/migrations/_log.system_entry`; `_log.py` says it is frozen |
| R15 | docs/erasure.md: three untrue sentences, records in the bin, backups, the unlogged step, who may run it | Rewritten |
| R16 | hr/0012's way back had an untested branch | The case added to `hr.tests.test_manager_rights` |
| R17 | The reports note named less than a report shows | Feed, harvest plans, treatments with medicines, health events, escapes, sea temperature named, three languages |
| R18 | Elapsed hours across a clock change; "ask your lead" for a lead; the wrong sentence for a clock-out before the clock-in | `forgotten_before` in UTC; "your lead, or whoever keeps attendance for you"; the times' rule runs before the overlap check |

Second pass of the review (one blocker, three minors), fixed:

| Finding | What was wrong | Fix |
|---|---|---|
| R19 blocker | A bracket inside a role or a phone made the whole contact list private: 3 lists and 8 people on the real data | The parser matches brackets and reads the details from the right-hand end; the dry run on the restored copy reports 0 lists made private whole and 0 parts |
| R20 | An address the form accepts but the parser's pattern did not stayed as the "role" | The parser reads an e-mail by `validate_email`, the form field's own validator |
| R21 | The database viewer and its CSV showed the digests | `audit_log.changes` is a masked column of the viewer |
| R22 | The erasure procedure's own log row tripped core.W004 | Its label is `Erased on request` (translated), not the private label `Note` |

Still open (said in docs/erasure.md): how long a database dump is kept and who deletes it (the dump taken before
core/0011 holds the whole log in plain text); names in the log, if the DPO wants them out; a logged page for erasing a
task note (today a database administrator's statement, which writes its own log row).
