# Bugs found in the aquaculture platform while porting the farm module

Porting the farm module tab by tab means reading its source closely. This document lists what was
found wrong, so it can be fixed in the platform and so the prototype does not repeat it. It grows
with every tab that is ported.

**Source read:** `aquaculture_platform`, branch `snowball-test`, commit `352aa2a8`
(`apps/farm-service`, `web/modules/farm-module`). Paths below are relative to those two folders.

**How reliable each entry is.** Findings come from reading the source. Those marked **✔** were
re-read by hand at the cited lines; the others are as reported by the analysis of the file and
should be confirmed at the cited place before fixing. Line numbers can drift with the branch.

**Severity:** **High** wrong or lost data, or a behaviour the user cannot work around;
**Medium** wrong in some cases, or a trap for later changes; **Low** inconsistency or polish.

**"In the prototype"** says how it is avoided here: by a database constraint, a shared mechanism
in `core/`, or by not porting the feature (satellite monitoring is deliberately left out).

## Contents

1. [Patterns that repeat across tabs](#patterns-that-repeat-across-tabs)
2. [Sites](#sites)
3. [Production departments](#production-departments) (the source calls them departments)
4. [Systems](#systems)

## Patterns that repeat across tabs

These are the root causes behind many of the single entries below. Fixing them once, where they
live, closes the whole class.

| Pattern | Where it shows | Root-cause fix |
|---|---|---|
| **A cleared field cannot be saved.** The forms send `value \|\| undefined`, and the API reads `undefined` as "no change". | Systems: department, parent system, description (SYS-01). Departments: notes (DEP-03). | Send `null` for a cleared optional field, and let the API treat `null` as "clear" and absent as "unchanged". One helper for every form. |
| **Rules that live only in the service code.** The database accepts what the service would refuse. | Name/code uniqueness, one primary contact, department/site match. | Put the rule in the database (unique index with a `WHERE`, check constraint, composite FK) and keep the service check only to give a readable message. |
| **Unique indexes that are not partial** while the services only check live rows. | Sites, departments, systems: a deleted record's code can never be reused, and the clash surfaces as a database error. | Make the unique index partial (`WHERE "isDeleted" = false`), or decide that codes are never reused and say so in the message. |
| **Input limits longer than the column.** | Site name/code/email, department name/code (SITE-01, DEP-01). | Generate the DTO limits from the entity, or add a test that compares them. |
| **Inputs accepted but never stored.** | Department `settings` and `area` (DEP-02), site `facilities`/`notes`/`metadata` (SITE-05). | Remove the field from the API, or add the column. |
| **Numbers without bounds.** Volumes, biomass, capacity and counts accept negative values and fractions. | Systems (SYS-03), departments (DEP-12), sites. | `@Min(0)` (and `@IsInt` for counts) on the DTO, `CHECK` on the column, `min` on the input. |
| **Foreign-key behaviour declared one way in the entity and another in the database.** | `ON DELETE CASCADE`/`SET NULL` in the entities, `RESTRICT` in all 62 baseline FKs. | Pick one source of truth (the migration) and generate or test the other against it. |
| **Soft delete and relations do not meet.** Handlers re-implement the consequences per entity, and the sets differ. | Site, department and system delete rules differ and each has gaps (SITE-06, DEP-08, SYS-08, SYS-09). | One delete mechanism that follows the relations (what the prototype's `core/softdelete.py` does). |
| **Lookups that forget `isDeleted`.** | Update/get of a deleted department and site; creating a system under a deleted site, department or parent. | Make the soft-delete filter part of the repository, not of each query. |
| **Enum and default drift.** | Department default type: database `production`, form `HATCHERY`, API requires it (DEP-09). | One default, defined once, in the database. |
| **Language mixed inside one screen.** | Delete dialogs are hard-coded Turkish inside an English UI; typo "silindığında". | Put every string in the message catalog. |

## Sites

| ID | Sev. | Where | What is wrong | In the prototype · Fix in the source |
|---|---|---|---|---|
| SITE-01 | Medium | `site/dto/create-site.input.ts` vs the `sites` columns | The DTO allows `name` 255, `code` 50 and `contactEmail` 255 characters; the columns are 150, 20 and 150. A longer value passes validation and then fails as a database error. | Column lengths are the limits, in the model and the form. · Align the DTO limits with the columns. |
| SITE-02 | Medium | `site/handlers/create-site.handler.ts:69-82`; unique indexes on `(tenantId, code)` and `(tenantId, name)` | The service checks name and code among live sites only, but the unique indexes are not partial. A deleted site's code and name still collide, and the user gets a raw database error instead of the "already exists" message. | Unique among live sites, as partial constraints; the form reports the clash on the field. · Make the indexes partial, or check deleted rows too and say so. |
| SITE-03 | Low | `site/entities/site-contact.entity.ts` vs Baseline | The entity declares `onDelete: CASCADE`; the database foreign key is `RESTRICT`. | Contacts follow their site. · See the FK pattern above. |
| SITE-04 | Medium | `site/handlers/upsert-site-contacts.handler.ts:273-278` | "At most one primary contact" is checked only in the handler. The partial unique index that enforced it existed only in an archived migration (`1788100000000`) and is not in the active schema. | Partial unique constraint in the database, and the form checks the list. · Restore the index in a new migration. |
| SITE-05 | Low | `site/dto/create-site.input.ts` | `waterCapacityM3`, `maxBiomassKg`, `establishedDate`, `facilities`, `notes` and `metadata` exist as columns but no input can set them. | Kept as columns, not offered in the form. · Add them to the input or drop the columns. |
| SITE-06 | High | `site/handlers/delete-site.handler.ts:61-66` | Without cascade, a site is blocked only by live **departments**. A site that has systems but no departments is deleted and its systems stay live, pointing at a deleted site. (Reported from the systems analysis.) | The delete follows every link of the site, so nothing is left pointing at it. · Block on, or cascade to, every dependent type. |
| SITE-07 | Medium | `site/handlers/update-site.handler.ts:189`; `upsert-site-contacts.handler.ts:284-289` | A deleted site can still be updated, and its contacts replaced; neither lookup filters `isDeleted`. | Deleted records are not reachable. · Filter in the repository. |
| SITE-08 | Low | `update-site.handler.ts:269-272`; `city`/`country` columns | City and country are stored twice (own columns and inside `address`) and one overwrites the other on update. | One flat set of address columns. · Keep a single copy. |
| SITE-09 | Low | `site/dto/create-site.input.ts` | `timezone` is free text (max 50, no check against real time zones). | A choice list. · Validate against the IANA list. |
| SITE-10 | Low | `site/entities/site.entity.ts` | `status` and `isActive` can disagree; there are no status transitions. | One field, `status`, is used. · Drop `isActive` or derive it. |
| SITE-11 | Low | `SitesTab.tsx` | A card shows `", "` when region and country are empty and `" m²"` when the area is empty. The empty state renders below an empty grid. Contact dialog and delete dialog texts are Turkish in an English UI. | Parts are shown only when present. · Fix the formatting and the catalog. |
| SITE-12 | Low | `CHK_sites_sea_cage_location` | Created `NOT VALID`, so existing sea-cage rows without coordinates are never checked. | Valid constraint. · `VALIDATE CONSTRAINT` after cleaning the data. |

## Production departments

The source names them departments and mixes in an `administration` type (an organisational department, which the prototype leaves to the HR module; see DEP-16). Entries keep the source's wording.

| ID | Sev. | Where | What is wrong | In the prototype · Fix in the source |
|---|---|---|---|---|
| DEP-01 | Medium | `department/dto/create-department.input.ts` vs `departments` columns | DTO allows `name` 255 and `code` 50; columns are 100 and 20. | Column lengths are the limits. · Align them. |
| DEP-02 | High | `department/dto/create-department.input.ts` | `settings` (capacity, temperature, water type, biosecurity level, certifications) and `area` are accepted and silently dropped: there are no columns for them. | Not offered. · Remove from the API or add columns. |
| DEP-03 | High | `DepartmentsTab.tsx` (list query in `hooks/useDepartments.ts:79-81`) | The list query never fetches `notes`, so the edit form always opens with empty notes. Saving empty notes sends `undefined`, which leaves the stored note unchanged: notes can be neither seen nor cleared. | The form loads from the record. · Fetch `notes`; send `null` to clear. |
| DEP-04 | Medium | `department/handlers/update-department.handler.ts:72` ✔ | `managerUserId: input.managerId ?? department.managerUserId`: because of `??` the manager can never be removed. The input is called `managerId`, the column and response `managerUserId`. | Manager is a user link that can be cleared. · Distinguish `null` from absent; one name. |
| DEP-05 | Medium | `department/handlers/create-department.handler.ts:47-62`; `departments` indexes | `(site, name)` uniqueness exists only in code and counts deleted rows; the `code` index is case-sensitive while the service upper-cases; both indexes are not partial. | Partial unique constraints among live departments (`code`; `site` + `name`). · Move the rules to the database. |
| DEP-06 | Medium | `update-department.handler.ts:38-44`; `get-department.handler.ts:108-111` | A deleted department can still be read and updated. | Not reachable. · Filter `isDeleted`. |
| DEP-07 | Low | `department.entity.ts`; update handler | `status`, `isActive` and `isDeleted` are meant to move together but nothing enforces it; update can set conflicting values. | One field, `status`. · Derive or drop the duplicate. |
| DEP-08 | High | `department/handlers/delete-department.handler.ts:88-133` | Deleting with cascade deactivates the tanks but does not delete them, while `tanks.departmentId` (NOT NULL, RESTRICT) keeps pointing at the deleted department. Systems are silently detached; sub-systems and feed inventory are left pointing at it; the dialog does not say so. | The delete follows the links and the confirmation lists what is affected. · Decide what happens to each dependent and show it. |
| DEP-09 | Low | entity default vs `DepartmentsTab.tsx` | Default type is `production` in the database and `HATCHERY` in the form; the API requires a type anyway. | One default. · Define it once. |
| DEP-10 | Low | `DepartmentsTab.tsx` | The site select is enabled when editing, but the site is not sent on update, so a change is silently ignored. | Site is read-only after creation and says so. · Disable it with an explanation. |
| DEP-11 | Medium | `DepartmentResponse`; `DepartmentsTab.tsx` | `currentLoad` is never filled in, so the capacity bar always reads 0 %. `contactEmail`/`contactPhone` are returned but have no column. Capacity is parsed as an integer though the column is a float. | Capacity is a decimal; no load bar until a load exists. · Compute or remove. |
| DEP-12 | Medium | `create-department.input.ts` | `capacity` has no minimum on the API (the input has `min=0`). | Check constraint and form validation. · `@Min(0)`. |
| DEP-13 | Low | `CodeGeneratorService.generateDepartmentCode` (`database/services/code-generator.service.ts:295`) | Written, never called: codes are typed by hand. | Typed by hand. · Use it or delete it. |
| DEP-14 | Low | `DepartmentsTab.tsx` | Two empty messages show at once; delete dialog in Turkish; frontend sends `cascade: true` always, so the non-cascade path is unreachable. | Single empty state. · Clean up. |
| DEP-15 | Medium | `DepartmentsTab.tsx` | The list is fetched with a fixed `limit: 100` and no pager: the 101st department is invisible. | Not limited. · Page or load all. |
| DEP-16 | Low | `department.entity.ts` (`DepartmentType.ADMINISTRATION`) | Production units and the company's organisational departments share one table and one type list, so a management department sits next to a hatchery hall. | Not ported: the HR module will own organisational departments. · Separate the two concepts. |

## Systems

| ID | Sev. | Where | What is wrong | In the prototype · Fix in the source |
|---|---|---|---|---|
| SYS-01 | High | `SystemsTab.tsx:273-290` ✔ | **Links and text cannot be cleared when editing.** `departmentId`, `parentSystemId` and `description` are sent as `value \|\| undefined`; picking "no department" sends `undefined`, which the API reads as "no change", so the old link stays. The API itself accepts an explicit `null`. | Cleared fields are saved as empty. · Send `null`; see the pattern table. |
| SYS-02 | High | `SystemsTab.tsx:201` ✔ | **The parent-system list excludes only the system itself, not its descendants.** A user can pick a child as the parent; the server then refuses with a circular-reference message, on update only. The list is also built from the already filtered list (search, site filter, "orphaned only"), so those filters shrink the choices. | The choices are the same-site systems that are not the system or any descendant. · Query candidates by site and exclude the subtree. |
| SYS-03 | High | `system/dto/create-system.input.ts:64-74` ✔ | **No bounds on numbers.** `totalVolumeM3`, `maxBiomassKg` and `tankCount` are only `@IsNumber()`: negatives pass, and `tankCount` accepts fractions. No `min` in the form either. | `CHECK >= 0`, whole numbers for counts, `min` on the inputs. · `@Min(0)`, `@IsInt()`. |
| SYS-04 | High | `system/handlers/update-system.handler.ts:97` ✔ | **Update assigns `departmentId` without any check:** no existence check, no same-site check, no deleted check. Create does check (`create-system.handler.ts:47-58`). A system can be moved onto a department of another site. | Department must belong to the system's site, as a constraint. · Reuse the create validation. |
| SYS-05 | Medium | `update-system.handler.ts:213-234`; `create-system.handler.ts:73-81` | Update does not check that a new parent's department matches; create accepts a child with any department when the parent has none. Create looks up site, department and parent without `isDeleted`. | A child is on the parent's site; checked in one place for create and update. · One validator. |
| SYS-06 | Low | `update-system.handler.ts:237-251` | `UpdateSystemInput` inherits `siteId` and silently ignores it. | Site is fixed after creation and the form says so. · Omit it from the input. |
| SYS-07 | Medium | `delete-system.handler.ts:183`; `get-system-delete-preview.handler.ts:340` | Create/update allow any depth; delete and its preview walk 10 levels. Descendants deeper than 10 stay live under a deleted parent. | The delete follows every level. · Remove the limit or enforce it on create. |
| SYS-08 | High | `delete-system.handler.ts:77` and `:96` ✔ | **Cascade delete never deactivates the equipment.** Step 1 hard-deletes the equipment links of the system and its descendants; step 3 then looks for those links, finds none, and deactivates nothing. Without cascade the equipment is deactivated even when it also serves another system. | Equipment links are removed with the system and the confirmation lists the equipment affected. · Read the links first; deactivate only equipment left with no system. |
| SYS-09 | High | `get-system-delete-preview.handler.ts:292-293`; `delete-system.handler.ts:125` | The preview always says "can delete" with no blockers; no tank or biomass check; `tanks.systemId` is left pointing at the deleted system; sub-systems are untouched. | Blockers come from the relations and from the model (fish in a tank). · Block on tanks with biomass; decide about the rest. |
| SYS-10 | Medium | Baseline FKs vs `system.entity.ts` | Every FK in the baseline is `RESTRICT`; the entities declare `CASCADE`/`SET NULL`. Because rows are only soft-deleted, nothing hard-cascades, so the difference stays hidden until a hard delete. | One definition (`on_delete`) drives the behaviour. · See the FK pattern. |
| SYS-11 | Medium | `tanks.systemId` (`tank.entity.ts:247`) | No foreign key in the database and no relation in the entity: a tank can point at a system that does not exist. | A real foreign key (when tanks are ported). · Add the FK. |
| SYS-12 | Low | `(tenantId, siteId, code)` unique index | Not partial; a deleted system's code cannot be reused. | Partial unique. · See the pattern table. |
| SYS-13 | Medium | `sub_systems`, `farm-seed.service.ts:509-528`, `equipment.subSystemId` | A dormant table: no DTO, resolver or handler. The seed inserts columns that do not exist (`equipmentCount`, `tankCount`) and enum values that do not exist (`'grow_out'`, `'active'`). `equipment.subSystemId` is never set. | Not ported. · Build it or remove the table, entity and seed. |
| SYS-14 | Low | `create-system.input.ts` | `type` is required by the API but has a database default of `other`; `tankCount` is typed by hand and can drift from the real tank count. | One default; the count is derived when tanks exist. · Compute it. |
| SYS-15 | Low | `SystemsTab.tsx` | The status badge shows the raw value (`OPERATIONAL`); the list is flat although systems nest; the delete dialog is Turkish; validation runs on create only; the list is capped at 100 without a pager. | Labels, hierarchy and no cap. · Polish. |
| SYS-16 | Low | `system/entities/system.entity.ts`, `site.entity.ts:5` | Comments describe Site → Department → System; the real model is Site → System with an optional link to a Department of the same site. | The model is as built. · Fix the comments. |
| SYS-17 | Medium | `system.resolver.ts:119-139` | Restore re-checks only the `(site, code)` uniqueness: it does not check that the site, parent or department are still live and does not bring back equipment links. | Restore re-validates the links. · Validate on restore. |
