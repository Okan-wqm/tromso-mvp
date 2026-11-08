from core.admin import register_audited

# The sensors configuration, deleted records too, and their restore (checked like a new record).
register_audited('sensors')
