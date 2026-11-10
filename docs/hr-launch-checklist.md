# HR and Production › Team: launch checklist

For the company's HR and its data-protection officer, before the HR pages (Company › HR and Production › Team) are used with
real people. Nothing on this list is encoded in the software as law: every figure the software holds is a default the owner
sets, and every item below is a decision or a duty of the company, not of the code. Statements about the law are marked
**not verified**: nobody on the development side consulted a legal source; each must be confirmed by HR or a lawyer.

Tick an item only when its owner has decided it and written down where the decision is kept.

## 1. Legal basis and information

| # | Item | Owner | Done |
|---|---|---|---|
| 1.1 | The legal basis for recording working time and punches (clock in, clock out, hand-entered presence) is written down (GDPR art. 6; **not verified**). | DPO | ☐ |
| 1.2 | Sick leave is health data (GDPR art. 9; **not verified**). The basis for keeping the leave **type** "sick" is written down, or a neutral type name is used. | DPO | ☐ |
| 1.3 | Attendance recording is a control measure: it is discussed with the employees' representatives and the employees are informed before it starts (Working Environment Act, chapter 9; **not verified**). | HR | ☐ |
| 1.4 | A screening for a data protection impact assessment is done and its result kept (GDPR art. 35; **not verified**). | DPO | ☐ |
| 1.5 | The privacy notice tells employees what this system records about them, who sees it (section 3) and for how long (section 4). | HR + DPO | ☐ |
| 1.6 | The shift plan is made known to the employees in good time; the Crew permission (section 3) is one way to do it. The required notice period is set by HR (**not verified**). | HR | ☐ |

## 2. Working time figures

The scheduling settings (Company › HR › Scheduling settings) hold the limits the shift schedule warns or blocks on: rest
between shifts, the standard week, the absence and punch windows. They start as labelled defaults, not as statutory figures.

| # | Item | Owner | Done |
|---|---|---|---|
| 2.1 | Every limit in Scheduling settings is set by HR to the figure the company applies, and whether each one warns or blocks. | HR | ☐ |
| 2.2 | It is understood that the rules run on the **planned** shifts only, not on the punches: a day worked longer than planned is not checked against a daily or weekly maximum (a later piece of work). | HR | ☐ |
| 2.3 | Night work, Sunday work and work by people under 18: none of these is modelled. HR confirms whether they occur and how they are handled outside the system. | HR | ☐ |
| 2.4 | "Clocked in" is not presence and not an emergency head count. A clock-in open longer than the limit HR sets in Scheduling settings (16 hours by default) is shown as "Clock-out forgotten", not as present, until a lead closes it with the real time; until that limit a forgotten clock-out still shows the person as present, and the On site now count keeps every open clock-in (it says how many are that old). The site's emergency routine does not rely on this system. HR confirms the limit (longer than the longest shift worked). | HR + safety | ☐ |

## 3. Who sees what

The software enforces this; HR confirms it is what the company wants and sets the roles accordingly (Company ›
Administration › Roles). `manage.py hr_roles` creates two starting roles, **Production manager** and **Production worker**,
once; it never changes a role an administrator has edited.

| Who | Sees | Never sees |
|---|---|---|
| The person | their own week, punches, leave requests with type and reason | |
| A colleague in the same production department, with **Crew** | name, shift code and times on the days both are in the department | note, leave, leave type, absence, punches, employee number, hours |
| A department manager, or a holder of **All production**, with Read on leave | the requests of their people with dates and status | the leave type unless they may also decide (Edit), the reason, the decision note |
| The same, with Edit on leave | the type and dates too, to replace a shift | the reason, the decision note |
| A holder of **Everyone** (HR) | everything about every person, office people in Company › HR, production people in Production › Team | |

| # | Item | Owner | Done |
|---|---|---|---|
| 3.1 | The roles above match the company's wishes; Crew is given or withheld per role. | HR | ☐ |
| 3.2 | Every person who is scheduled or clocks in has an employee record (students and advisors too); a person who never signs in has no account. | HR | ☐ |
| 3.3 | Only holders of Everyone link an account to a person (the account decides who reads the person's own words). The list of holders is short and named. | HR | ☐ |
| 3.4 | Nobody decides their own leave (the database refuses it). Each production department has a second decider when its manager is away (a head of production with All production, or HR). | HR | ☐ |

## 4. Keeping and deleting

| # | Item | Owner | Done |
|---|---|---|---|
| 4.1 | A retention period is set for leave requests, plans, punches and placements, and who deletes them when it runs out. | DPO | ☐ |
| 4.2 | The activity log cannot be deleted, by design, and it records changes to people's HR records (never the words of a leave reason or a note; never a contact's e-mail or phone or the text of a task note either: [erasure.md](erasure.md)). Whether this conflicts with 4.1, and how, is decided by the owner. | Owner + DPO | ☐ |
| 4.3 | The database viewer is given to nobody outside IT administration. | Owner | ☐ |

## 5. Sign-off

| Role | Name | Date |
|---|---|---|
| HR | | |
| Data-protection officer | | |
| Owner | | |
