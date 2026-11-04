from core.admin import register_audited

# The HR records, deleted ones too, and their restore (checked like a new record: refused while a department or a
# person they point at is deleted).
register_audited('hr')
