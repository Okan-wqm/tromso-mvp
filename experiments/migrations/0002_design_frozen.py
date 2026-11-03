"""A started experiment's design cannot change: the database itself refuses it, whatever writes (pre-registration: what
was planned is what is judged). The forms and the services say it in readable messages first (`design.problems`,
`services`); these triggers make the rule hold for any other writer, a script or a hand-typed UPDATE.

- `experiments`: once the status is not draft, every column but the status (forward only: draft, running, closed), the
  name, the notes and the bookkeeping columns is fixed, and the row is never deleted (a soft delete changes
  `is_deleted`, so it is refused too).
- factors, levels, groups, group levels and replicates: no insert, update or delete unless the owning experiment is a
  draft.
- placements: a draft's are free; a running experiment may get a new one (a replacement) and shorten one (`until_on`,
  never longer) and say why (`left_reason`); a closed one allows nothing; a placement of a started experiment is never
  deleted; a template has none at all.

A change of the user columns alone (`created_by_id`, `updated_by_id`, `deleted_by_id`) is always let through: removing a
person from the system sets them to NULL, and that must not be blocked by what they once created (as the filed
regulatory reports' triggers). The team (`experiment_members`) is not the design and is not guarded.
Refusals are `check_violation`, so the ORM raises them as `IntegrityError` like a constraint."""
from django.db import migrations

USER_COLUMNS = "'created_by_id' - 'updated_by_id' - 'deleted_by_id'"

FROZEN = f"""
-- The experiment a row belongs to, whichever of its parts it is a part of: `$1` is the kind of reference (the experiment
-- itself, a factor, a group, a replicate) and `$2` its id. Positional, not named: a factor has a column called kind,
-- which would be read in place of a parameter of that name.
CREATE FUNCTION owning_experiment(text, uuid) RETURNS experiments AS $$
    SELECT e.* FROM experiments e WHERE $1 = 'experiment' AND e.id = $2
    UNION ALL
    SELECT e.* FROM experiment_factors f JOIN experiments e ON e.id = f.experiment_id
        WHERE $1 = 'factor' AND f.id = $2
    UNION ALL
    SELECT e.* FROM experiment_groups g JOIN experiments e ON e.id = g.experiment_id
        WHERE $1 = 'group' AND g.id = $2
    UNION ALL
    SELECT e.* FROM experiment_replicates r JOIN experiment_groups g ON g.id = r.group_id
        JOIN experiments e ON e.id = g.experiment_id WHERE $1 = 'replicate' AND r.id = $2
$$ LANGUAGE sql STABLE;

CREATE FUNCTION experiment_frozen() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.status <> 'draft' THEN
            RAISE EXCEPTION 'experiment % has started: it is never deleted', OLD.code USING ERRCODE = 'check_violation';
        END IF;
        RETURN OLD;
    END IF;
    IF NEW.status <> OLD.status
       AND (OLD.status, NEW.status) NOT IN (('draft', 'running'), ('running', 'closed')) THEN
        RAISE EXCEPTION 'experiment %: the status goes from draft to running to closed, not from % to %',
            OLD.code, OLD.status, NEW.status USING ERRCODE = 'check_violation';
    END IF;
    IF OLD.status = 'draft' THEN
        RETURN NEW;
    END IF;
    IF (to_jsonb(NEW) - 'status' - 'name' - 'notes' - 'version' - 'updated_at' - {USER_COLUMNS})
       IS DISTINCT FROM (to_jsonb(OLD) - 'status' - 'name' - 'notes' - 'version' - 'updated_at' - {USER_COLUMNS}) THEN
        RAISE EXCEPTION 'experiment % has started: its design cannot change', OLD.code USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_experiments_frozen
    BEFORE UPDATE OR DELETE ON experiments
    FOR EACH ROW EXECUTE FUNCTION experiment_frozen();

CREATE FUNCTION experiment_design_frozen() RETURNS trigger AS $$
DECLARE
    owner experiments;
BEGIN
    IF TG_OP = 'UPDATE'
       AND (to_jsonb(NEW) - {USER_COLUMNS}) IS NOT DISTINCT FROM (to_jsonb(OLD) - {USER_COLUMNS}) THEN
        RETURN NEW;
    END IF;
    IF TG_OP <> 'INSERT' THEN
        SELECT * INTO owner FROM owning_experiment(TG_ARGV[0], (to_jsonb(OLD) ->> TG_ARGV[1])::uuid);
        IF owner.status <> 'draft' THEN
            RAISE EXCEPTION 'experiment % has started: its design cannot change', owner.code
                USING ERRCODE = 'check_violation';
        END IF;
    END IF;
    IF TG_OP <> 'DELETE' THEN
        SELECT * INTO owner FROM owning_experiment(TG_ARGV[0], (to_jsonb(NEW) ->> TG_ARGV[1])::uuid);
        IF owner.status <> 'draft' THEN
            RAISE EXCEPTION 'experiment % has started: its design cannot change', owner.code
                USING ERRCODE = 'check_violation';
        END IF;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_experiment_factors_frozen
    BEFORE INSERT OR UPDATE OR DELETE ON experiment_factors
    FOR EACH ROW EXECUTE FUNCTION experiment_design_frozen('experiment', 'experiment_id');
CREATE TRIGGER trg_experiment_groups_frozen
    BEFORE INSERT OR UPDATE OR DELETE ON experiment_groups
    FOR EACH ROW EXECUTE FUNCTION experiment_design_frozen('experiment', 'experiment_id');
CREATE TRIGGER trg_experiment_group_levels_frozen
    BEFORE INSERT OR UPDATE OR DELETE ON experiment_group_levels
    FOR EACH ROW EXECUTE FUNCTION experiment_design_frozen('experiment', 'experiment_id');
CREATE TRIGGER trg_experiment_levels_frozen
    BEFORE INSERT OR UPDATE OR DELETE ON experiment_levels
    FOR EACH ROW EXECUTE FUNCTION experiment_design_frozen('factor', 'factor_id');
CREATE TRIGGER trg_experiment_replicates_frozen
    BEFORE INSERT OR UPDATE OR DELETE ON experiment_replicates
    FOR EACH ROW EXECUTE FUNCTION experiment_design_frozen('group', 'group_id');

CREATE FUNCTION experiment_placement_frozen() RETURNS trigger AS $$
DECLARE
    owner experiments;
    was experiments;
BEGIN
    IF TG_OP = 'UPDATE'
       AND (to_jsonb(NEW) - {USER_COLUMNS}) IS NOT DISTINCT FROM (to_jsonb(OLD) - {USER_COLUMNS}) THEN
        RETURN NEW;
    END IF;
    IF TG_OP <> 'DELETE' THEN
        SELECT * INTO owner FROM owning_experiment('replicate', NEW.replicate_id);
        IF owner.is_template THEN
            RAISE EXCEPTION 'experiment % is a template: it has no tanks', owner.code
                USING ERRCODE = 'check_violation';
        END IF;
        IF owner.status = 'closed' THEN
            RAISE EXCEPTION 'experiment % is closed: its placements cannot change', owner.code
                USING ERRCODE = 'check_violation';
        END IF;
    END IF;
    IF TG_OP = 'INSERT' THEN
        RETURN NEW;                                   -- a draft's, or a running experiment's replacement
    END IF;
    SELECT * INTO was FROM owning_experiment('replicate', OLD.replicate_id);
    IF was.status = 'draft' THEN
        IF TG_OP = 'UPDATE' AND owner.status <> 'draft' THEN
            RAISE EXCEPTION 'a placement of a draft cannot be moved into experiment %, which has started', owner.code
                USING ERRCODE = 'check_violation';
        END IF;
        IF TG_OP = 'DELETE' THEN
            RETURN OLD;
        END IF;
        RETURN NEW;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'a placement of experiment % is never deleted: shorten it', was.code
            USING ERRCODE = 'check_violation';
    END IF;
    IF was.status = 'closed' THEN
        RAISE EXCEPTION 'experiment % is closed: its placements cannot change', was.code
            USING ERRCODE = 'check_violation';
    END IF;
    IF (to_jsonb(NEW) - 'until_on' - 'left_reason' - 'version' - 'updated_at' - {USER_COLUMNS})
       IS DISTINCT FROM (to_jsonb(OLD) - 'until_on' - 'left_reason' - 'version' - 'updated_at' - {USER_COLUMNS})
       OR NEW.until_on > OLD.until_on THEN
        RAISE EXCEPTION 'a placement of experiment % can only be shortened, with its reason', was.code
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_experiment_replicate_units_frozen
    BEFORE INSERT OR UPDATE OR DELETE ON experiment_replicate_units
    FOR EACH ROW EXECUTE FUNCTION experiment_placement_frozen();
"""

DROP = """
DROP TRIGGER IF EXISTS trg_experiment_replicate_units_frozen ON experiment_replicate_units;
DROP FUNCTION IF EXISTS experiment_placement_frozen();
DROP TRIGGER IF EXISTS trg_experiment_replicates_frozen ON experiment_replicates;
DROP TRIGGER IF EXISTS trg_experiment_levels_frozen ON experiment_levels;
DROP TRIGGER IF EXISTS trg_experiment_group_levels_frozen ON experiment_group_levels;
DROP TRIGGER IF EXISTS trg_experiment_groups_frozen ON experiment_groups;
DROP TRIGGER IF EXISTS trg_experiment_factors_frozen ON experiment_factors;
DROP FUNCTION IF EXISTS experiment_design_frozen();
DROP TRIGGER IF EXISTS trg_experiments_frozen ON experiments;
DROP FUNCTION IF EXISTS experiment_frozen();
DROP FUNCTION IF EXISTS owning_experiment(text, uuid);
"""


class Migration(migrations.Migration):
    dependencies = [('experiments', '0001_initial')]

    operations = [migrations.RunSQL(FROZEN, reverse_sql=DROP)]
