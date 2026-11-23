# State of wip/exp-access (2026-11-23)

Main merged twice (last 635a83fb). The whole suite is green on db6fc851
(https://github.com/Okan-wqm/tromso-mvp/actions/runs/45260914058, 5171 tests), the route walk and the lists'
comparison included.

Done: steps 1 to 9, 11 and 12 of `F:\dev\balik-notes\plan\exp-access\PLAN.md`, owner amendments C1 to C4. That
covers:
- the experiments' own seal, sharing, Who looked;
- the open, sealed and private audiences;
- the farm, task, sensor, alarm and monitoring seals;
- the database viewer narrowed, and an export that needs a reason;
- reports and medicine withdrawal read as the system;
- Oversee and its card, with migration 0005;
- the preflight command, the budget tests and the README.

Dropped by the owner (23.11.2026): step 10, guest accounts and django-otp. An outside researcher is an ordinary
account the platform admin makes, with the Research collaborator role (`manage.py experiments_roles`); the lead adds
them to the team or shares a part with them (README › Research › Experiments, Confidentiality).

Not done:
- The lead's phone on the Oversee card. Owner amendment C3 asks for it, but HR keeps no contact detail on an employee,
  and a test holds that rule.

Before landing:
- `core/0015_access_event` follows main's `core/0014_rev` (renumbered when core-rev landed).
- Remove this file.
