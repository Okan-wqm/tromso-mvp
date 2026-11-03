from core.admin import register_audited

# Tasks and recurring tasks, deleted ones too, and their restore (checked like a new record: refused while their
# place is deleted).
register_audited('tasks')
