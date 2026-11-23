# Written by hand: the functions and triggers.
"""A live unit is in a live production department on a live site (F-212, cross review F1). Three constraint triggers
hold it across the tables, as far as a row may be checked on its own write:

- a unit written live (created, moved to another department, restored) is in a live department whose site, when it
  has one, is live (`trg_units_on_a_live_site`);
- a production department is deleted only once it has no live unit, and is live only on a live site
  (`trg_departments_on_a_live_site`);
- a site is deleted only once it has no live production department (`trg_sites_without_live_departments`).

A department without a site is the NOT VALID check's matter (migration 0029): these triggers let such a legacy row be,
so the fish in its units can still be moved or harvested out. `manage.py check_stock` names every row that breaks the
rule from before. The delete plan deletes children before their parent and a restore brings parents back first, so
neither meets these triggers; a write that slips between a site's delete and a unit's save (the unit's save locks
its site and department, `Tank.save`) is refused here."""
from django.db import migrations

FUNCTIONS = """
CREATE FUNCTION farm_unit_on_a_live_site() RETURNS trigger AS $$
DECLARE
    department_deleted boolean;
    site_deleted boolean;
BEGIN
    IF NEW.is_deleted THEN
        RETURN NULL;
    END IF;
    SELECT d.is_deleted, s.is_deleted INTO department_deleted, site_deleted
        FROM production_departments d LEFT JOIN sites s ON s.id = d.site_id WHERE d.id = NEW.production_department_id;
    IF department_deleted OR coalesce(site_deleted, false) THEN
        RAISE EXCEPTION 'Unit % is in a deleted production department or on a deleted site: choose a live one',
            NEW.code USING ERRCODE = 'check_violation', CONSTRAINT = 'trg_units_on_a_live_site';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER trg_units_on_a_live_site
    AFTER INSERT OR UPDATE OF production_department_id, is_deleted ON tanks
    FOR EACH ROW EXECUTE FUNCTION farm_unit_on_a_live_site();

CREATE FUNCTION farm_department_on_a_live_site() RETURNS trigger AS $$
BEGIN
    IF NEW.is_deleted THEN
        IF EXISTS (SELECT 1 FROM tanks WHERE production_department_id = NEW.id AND NOT is_deleted) THEN
            RAISE EXCEPTION 'Production department % still has live units: delete or move them first', NEW.code
                USING ERRCODE = 'check_violation', CONSTRAINT = 'trg_departments_on_a_live_site';
        END IF;
    ELSIF EXISTS (SELECT 1 FROM sites WHERE id = NEW.site_id AND is_deleted) THEN
        RAISE EXCEPTION 'Production department % is on a deleted site: restore the site first', NEW.code
            USING ERRCODE = 'check_violation', CONSTRAINT = 'trg_departments_on_a_live_site';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER trg_departments_on_a_live_site
    AFTER INSERT OR UPDATE OF site_id, is_deleted ON production_departments
    FOR EACH ROW EXECUTE FUNCTION farm_department_on_a_live_site();

CREATE FUNCTION farm_site_without_live_departments() RETURNS trigger AS $$
BEGIN
    IF NEW.is_deleted AND EXISTS (
        SELECT 1 FROM production_departments WHERE site_id = NEW.id AND NOT is_deleted
    ) THEN
        RAISE EXCEPTION 'Site % still has live production departments: delete them with it', NEW.code
            USING ERRCODE = 'check_violation', CONSTRAINT = 'trg_sites_without_live_departments';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER trg_sites_without_live_departments
    AFTER UPDATE OF is_deleted ON sites
    FOR EACH ROW EXECUTE FUNCTION farm_site_without_live_departments();
"""

DROP = """
DROP TRIGGER trg_sites_without_live_departments ON sites;
DROP FUNCTION farm_site_without_live_departments();
DROP TRIGGER trg_departments_on_a_live_site ON production_departments;
DROP FUNCTION farm_department_on_a_live_site();
DROP TRIGGER trg_units_on_a_live_site ON tanks;
DROP FUNCTION farm_unit_on_a_live_site();
"""


class Migration(migrations.Migration):

    dependencies = [
        ('farm', '0029_departments_on_a_site'),
    ]

    operations = [migrations.RunSQL(FUNCTIONS, DROP)]
