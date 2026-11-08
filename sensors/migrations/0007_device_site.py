# Written by hand: the functions and triggers, and an alarm event's place (its binding), backfilled.
"""A device is at one site at a time (portable sensors): the site of the places its channels are bound to now.
Constraint triggers hold it, with `sensors_place_site`, the site of a binding's place (a sampling point's owner's: a
unit's or a piece of equipment's production department's, a system's own; NULL for a department without a site):

- an open live binding (no end, not deleted) is to a place of its channel's device's site, or of no site;
- a device's site changes only while none of its channels (deleted ones too: their bindings come back with them) has an
  open live binding to a place of another site;
- a unit or a piece of equipment (its production department), a system or a production department (its site) changes
  site only while no device is placed there (`trg_sensors_placed_site`: move the device or take it out first), so a
  placed device's site never lags its place. An update of an open binding that leaves its place as it was (a note) is
  never checked.

`sensors/bindings.py` `move_device` ends the open bindings, moves the device's site, then opens the new ones, in one
transaction. A closed binding is history and is never checked. Rows already breaking the rule stop the migration, named:
a device bound at two sites is a decision for a person, never made here.

An alarm event belongs to the place it opened at: `AlarmEvent.binding`, filled for the events already there with the
binding their channel held when they opened (sensors/alarms.py)."""
import django.db.models.deletion
from django.db import migrations, models

FUNCTIONS = """
CREATE FUNCTION sensors_place_site(p_point uuid, p_system uuid, p_equipment uuid) RETURNS uuid AS $$
    SELECT CASE
        WHEN p_system IS NOT NULL THEN (SELECT site_id FROM systems WHERE id = p_system)
        WHEN p_equipment IS NOT NULL THEN (
            SELECT d.site_id FROM equipment e JOIN production_departments d ON d.id = e.production_department_id
            WHERE e.id = p_equipment)
        ELSE (
            SELECT coalesce(s.site_id, ud.site_id, ed.site_id)
            FROM water_sampling_points p
            LEFT JOIN systems s ON s.id = p.system_id
            LEFT JOIN tanks t ON t.id = p.unit_id
            LEFT JOIN production_departments ud ON ud.id = t.production_department_id
            LEFT JOIN equipment e ON e.id = p.equipment_id
            LEFT JOIN production_departments ed ON ed.id = e.production_department_id
            WHERE p.id = p_point)
    END
$$ LANGUAGE sql STABLE;

CREATE FUNCTION sensors_binding_site() RETURNS trigger AS $$
DECLARE
    device_site uuid;
    device_code varchar;
    place_site uuid;
BEGIN
    IF NEW.is_deleted OR NEW.valid_to IS NOT NULL THEN
        RETURN NULL;
    END IF;
    IF TG_OP = 'UPDATE' AND NOT OLD.is_deleted AND OLD.valid_to IS NULL AND OLD.channel_id = NEW.channel_id
       AND OLD.point_id IS NOT DISTINCT FROM NEW.point_id AND OLD.system_id IS NOT DISTINCT FROM NEW.system_id
       AND OLD.equipment_id IS NOT DISTINCT FROM NEW.equipment_id THEN
        RETURN NULL;                    -- the same open binding at the same place: a note, its version
    END IF;
    SELECT d.site_id, d.code INTO device_site, device_code
        FROM sensors_channel c JOIN sensors_device d ON d.id = c.device_id WHERE c.id = NEW.channel_id;
    place_site := sensors_place_site(NEW.point_id, NEW.system_id, NEW.equipment_id);
    IF place_site IS NOT NULL AND place_site <> device_site THEN
        RAISE EXCEPTION 'Device % is at another site: a channel goes to another site with its whole device (Move device)',
            device_code USING ERRCODE = 'check_violation', CONSTRAINT = 'trg_sensors_binding_site';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER trg_sensors_binding_site
    AFTER INSERT OR UPDATE ON sensors_binding
    FOR EACH ROW EXECUTE FUNCTION sensors_binding_site();

CREATE FUNCTION sensors_device_site() RETURNS trigger AS $$
BEGIN
    IF NEW.site_id IS DISTINCT FROM OLD.site_id AND EXISTS (
        SELECT 1 FROM sensors_binding b JOIN sensors_channel c ON c.id = b.channel_id
        WHERE c.device_id = NEW.id AND NOT b.is_deleted AND b.valid_to IS NULL
          AND coalesce(sensors_place_site(b.point_id, b.system_id, b.equipment_id), NEW.site_id) <> NEW.site_id
    ) THEN
        RAISE EXCEPTION 'Device % is placed at its site now: move the device (Move device) or take it out first',
            NEW.code USING ERRCODE = 'check_violation', CONSTRAINT = 'trg_sensors_device_site';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER trg_sensors_device_site
    AFTER UPDATE OF site_id ON sensors_device
    FOR EACH ROW EXECUTE FUNCTION sensors_device_site();

CREATE FUNCTION sensors_placed_site() RETURNS trigger AS $$
DECLARE
    misplaced varchar;
BEGIN
    SELECT d.code INTO misplaced
    FROM sensors_binding b JOIN sensors_channel c ON c.id = b.channel_id JOIN sensors_device d ON d.id = c.device_id
    WHERE NOT b.is_deleted AND b.valid_to IS NULL
      AND coalesce(sensors_place_site(b.point_id, b.system_id, b.equipment_id), d.site_id) <> d.site_id
    LIMIT 1;
    IF misplaced IS NOT NULL THEN
        RAISE EXCEPTION 'Sensor device % is placed here: move the device (Move device) or take it out of the water first',
            misplaced USING ERRCODE = 'check_violation', CONSTRAINT = 'trg_sensors_placed_site';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER trg_sensors_placed_site AFTER UPDATE OF production_department_id ON tanks
    FOR EACH ROW WHEN (OLD.production_department_id IS DISTINCT FROM NEW.production_department_id)
    EXECUTE FUNCTION sensors_placed_site();
CREATE CONSTRAINT TRIGGER trg_sensors_placed_site AFTER UPDATE OF production_department_id ON equipment
    FOR EACH ROW WHEN (OLD.production_department_id IS DISTINCT FROM NEW.production_department_id)
    EXECUTE FUNCTION sensors_placed_site();
CREATE CONSTRAINT TRIGGER trg_sensors_placed_site AFTER UPDATE OF site_id ON systems
    FOR EACH ROW WHEN (OLD.site_id IS DISTINCT FROM NEW.site_id)
    EXECUTE FUNCTION sensors_placed_site();
CREATE CONSTRAINT TRIGGER trg_sensors_placed_site AFTER UPDATE OF site_id ON production_departments
    FOR EACH ROW WHEN (OLD.site_id IS DISTINCT FROM NEW.site_id)
    EXECUTE FUNCTION sensors_placed_site();

DO $$
DECLARE
    misplaced text;
BEGIN
    SELECT string_agg(DISTINCT d.code, ', ') INTO misplaced
    FROM sensors_binding b JOIN sensors_channel c ON c.id = b.channel_id JOIN sensors_device d ON d.id = c.device_id
    WHERE NOT b.is_deleted AND b.valid_to IS NULL
      AND coalesce(sensors_place_site(b.point_id, b.system_id, b.equipment_id), d.site_id) <> d.site_id;
    IF misplaced IS NOT NULL THEN
        RAISE EXCEPTION 'Devices bound now to a place of another site than their own: %. Move or unbind them first.',
            misplaced;
    END IF;
END;
$$;
"""
EVENT_PLACES = """
UPDATE sensors_alarm_event e SET binding_id = b.id
FROM sensors_binding b JOIN sensors_channel c ON c.id = b.channel_id
WHERE c.channel_no = e.channel_no AND NOT b.is_deleted AND b.valid_from <= e.opened_at
  AND (b.valid_to IS NULL OR b.valid_to > e.opened_at);
"""
DROP = """
DROP TRIGGER IF EXISTS trg_sensors_placed_site ON production_departments;
DROP TRIGGER IF EXISTS trg_sensors_placed_site ON systems;
DROP TRIGGER IF EXISTS trg_sensors_placed_site ON equipment;
DROP TRIGGER IF EXISTS trg_sensors_placed_site ON tanks;
DROP FUNCTION IF EXISTS sensors_placed_site();
DROP TRIGGER IF EXISTS trg_sensors_device_site ON sensors_device;
DROP FUNCTION IF EXISTS sensors_device_site();
DROP TRIGGER IF EXISTS trg_sensors_binding_site ON sensors_binding;
DROP FUNCTION IF EXISTS sensors_binding_site();
DROP FUNCTION IF EXISTS sensors_place_site(uuid, uuid, uuid);
"""


class Migration(migrations.Migration):

    dependencies = [
        ('sensors', '0006_ingest_requests'),
    ]

    operations = [
        migrations.RunSQL(FUNCTIONS, reverse_sql=DROP),
        migrations.AddField(
            model_name='alarmevent',
            name='binding',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                    related_name='alarm_events', to='sensors.binding', verbose_name='Place (binding)'),
        ),
        migrations.RunSQL(EVENT_PLACES, reverse_sql=migrations.RunSQL.noop),
    ]
