from core.admin import register_audited

# The HR records, deleted ones too. The departments, shifts, holidays and leave types have their restore (checked like
# a new record: refused while a record they point at is deleted); the people, their placements, plans, leave requests
# and attendance have none: hr.services is their one writer, and a voided one is entered again on its page.
register_audited('hr')
