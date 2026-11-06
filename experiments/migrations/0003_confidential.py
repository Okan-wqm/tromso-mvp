"""Experiment confidentiality and whole-system booking (core.sealing, experiments.sealing): who may read an experiment
(its audience, sealed by default; its team's windows and the guest role; the shares given by its lead), the approval it runs
under and whom to call (the card a person overseeing its tanks sees), the whole-system bookings with their tagged
placements, and the sealed cells as a view. Existing experiments become sealed, their rows stay valid (every new column has
a default or is empty).

The database holds: a started experiment still changes its audience, approval and contact (the frozen trigger of 0002
widened, nothing else); a booking's placements are tanks of its system, in its replicate, on its days; a booking is not
shortened past them and follows the placements' frozen rule; no tank joins or leaves a system booked from today on, and no
booked system is moved under another; the view `experiment_cells` is the one definition of who is in which cell when."""
from importlib import import_module

import core.ranges
import datetime
import django.contrib.postgres.constraints
import django.db.models.deletion
import django.db.models.expressions
import django.utils.timezone
import uuid

from django.conf import settings
from django.db import migrations, models


USER_COLUMNS = "'created_by_id' - 'updated_by_id' - 'deleted_by_id'"

# The started experiment's columns that stay editable: its status, name and notes (migration 0002) and now who may read
# it (audience) and the approval it runs under (the card's fields).
FROZEN_V2 = f"""
CREATE OR REPLACE FUNCTION experiment_frozen() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.status <> 'draft' THEN
            RAISE EXCEPTION 'experiment %: it is made a draft and started by its Start, not made %', NEW.code, NEW.status
                USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    END IF;
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
    IF NEW.is_template AND NOT OLD.is_template AND EXISTS (
        SELECT 1 FROM experiment_replicate_units u JOIN experiment_replicates r ON r.id = u.replicate_id
            JOIN experiment_groups g ON g.id = r.group_id WHERE g.experiment_id = NEW.id) THEN
        RAISE EXCEPTION 'experiment %: a template has no placements', NEW.code USING ERRCODE = 'check_violation';
    END IF;
    IF OLD.status = 'draft' THEN
        RETURN NEW;
    END IF;
    IF (to_jsonb(NEW) - 'status' - 'name' - 'notes' - 'audience' - 'approval_ref' - 'approval_valid_until'
        - 'contact_phone' - 'version' - 'updated_at' - {USER_COLUMNS})
       IS DISTINCT FROM (to_jsonb(OLD) - 'status' - 'name' - 'notes' - 'audience' - 'approval_ref'
        - 'approval_valid_until' - 'contact_phone' - 'version' - 'updated_at' - {USER_COLUMNS}) THEN
        RAISE EXCEPTION 'experiment % has started: its design cannot change', OLD.code USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

BOOKING = """
-- A booking's placements are its system's tanks, in its replicate, on its days.
CREATE FUNCTION experiment_booking_tag() RETURNS trigger AS $$
DECLARE
    b experiment_replicate_systems;
BEGIN
    IF NEW.booking_id IS NULL THEN
        RETURN NEW;
    END IF;
    SELECT * INTO b FROM experiment_replicate_systems WHERE id = NEW.booking_id;
    IF b.replicate_id <> NEW.replicate_id OR NEW.from_on < b.from_on OR NEW.until_on > b.until_on
       OR NOT EXISTS (SELECT 1 FROM tanks t WHERE t.id = NEW.unit_id AND t.system_id = b.system_id) THEN
        RAISE EXCEPTION 'a placement of booking % is a tank of its system, in its replicate, on its days', b.id
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_experiment_replicate_units_booking
    BEFORE INSERT OR UPDATE ON experiment_replicate_units
    FOR EACH ROW EXECUTE FUNCTION experiment_booking_tag();

-- A booking's days hold its live placements: it is never shortened past one of them, never moved to another replicate.
CREATE FUNCTION experiment_booking_holds() RETURNS trigger AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM experiment_replicate_units u WHERE u.booking_id = NEW.id AND NOT u.is_deleted
               AND (u.from_on < NEW.from_on OR u.until_on > NEW.until_on OR u.replicate_id <> NEW.replicate_id))
       AND NOT NEW.is_deleted THEN
        RAISE EXCEPTION 'booking %: its days hold its tanks'' placements; shorten them first', NEW.id
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_experiment_replicate_systems_holds
    BEFORE UPDATE ON experiment_replicate_systems
    FOR EACH ROW EXECUTE FUNCTION experiment_booking_holds();

-- The started experiment's bookings follow its placements' rule (migration 0002): shortened only, never deleted.
CREATE TRIGGER trg_experiment_replicate_systems_frozen
    BEFORE INSERT OR UPDATE OR DELETE ON experiment_replicate_systems
    FOR EACH ROW EXECUTE FUNCTION experiment_placement_frozen();

-- Whether a system, or a system above it, is booked on a day from today on (a live booking of a live experiment).
CREATE FUNCTION system_booked_from_today(uuid) RETURNS boolean AS $$
    WITH RECURSIVE up(id) AS (
        SELECT $1
        UNION
        SELECT s.parent_id FROM systems s JOIN up ON s.id = up.id WHERE s.parent_id IS NOT NULL)
    SELECT EXISTS (
        SELECT 1 FROM experiment_replicate_systems b
            JOIN experiment_replicates r ON r.id = b.replicate_id AND NOT r.is_deleted
            JOIN experiment_groups g ON g.id = r.group_id AND NOT g.is_deleted
            JOIN experiments e ON e.id = g.experiment_id AND NOT e.is_deleted
        WHERE b.system_id IN (SELECT id FROM up) AND NOT b.is_deleted AND b.until_on >= current_date)
$$ LANGUAGE sql STABLE;

-- A tank does not join or leave a booked system: the booking's placements are the tanks it held.
CREATE FUNCTION tank_system_booked() RETURNS trigger AS $$
BEGIN
    IF (TG_OP = 'INSERT' AND NEW.system_id IS NOT NULL AND system_booked_from_today(NEW.system_id))
       OR (TG_OP = 'UPDATE' AND NEW.system_id IS DISTINCT FROM OLD.system_id
           AND ((OLD.system_id IS NOT NULL AND system_booked_from_today(OLD.system_id))
                OR (NEW.system_id IS NOT NULL AND system_booked_from_today(NEW.system_id)))) THEN
        RAISE EXCEPTION 'unit %: its system is booked to an experiment; a unit joins or leaves it after the booking',
            NEW.code USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_tanks_system_booked
    BEFORE INSERT OR UPDATE OF system_id ON tanks
    FOR EACH ROW EXECUTE FUNCTION tank_system_booked();

-- A booked system is not put under another system, and nothing booked is put under it.
CREATE FUNCTION system_parent_booked() RETURNS trigger AS $$
BEGIN
    IF NEW.parent_id IS DISTINCT FROM OLD.parent_id AND (
        system_booked_from_today(NEW.id)
        OR (OLD.parent_id IS NOT NULL AND system_booked_from_today(OLD.parent_id))
        OR (NEW.parent_id IS NOT NULL AND system_booked_from_today(NEW.parent_id))
        OR EXISTS (WITH RECURSIVE down(id) AS (
                       SELECT NEW.id UNION SELECT s.id FROM systems s JOIN down ON s.parent_id = down.id)
                   SELECT 1 FROM down WHERE system_booked_from_today(down.id))) THEN
        RAISE EXCEPTION 'system %: it, a system above it or one below it is booked to an experiment', NEW.code
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_systems_parent_booked
    BEFORE UPDATE OF parent_id ON systems
    FOR EACH ROW EXECUTE FUNCTION system_parent_booked();

-- The sealed cells: who is in which tank or system on which days, for the seal (core.sealing). Live rows of live
-- experiments whose audience is sealed, drafts included (a draft reserves); a template has no placements.
CREATE VIEW experiment_cells AS
    SELECT u.id, u.unit_id, NULL::uuid AS system_id, u.from_on, u.until_on, g.experiment_id
    FROM experiment_replicate_units u
        JOIN experiment_replicates r ON r.id = u.replicate_id AND NOT r.is_deleted
        JOIN experiment_groups g ON g.id = r.group_id AND NOT g.is_deleted
        JOIN experiments e ON e.id = g.experiment_id AND NOT e.is_deleted AND e.audience = 'sealed'
    WHERE NOT u.is_deleted
    UNION ALL
    SELECT b.id, NULL::uuid, b.system_id, b.from_on, b.until_on, g.experiment_id
    FROM experiment_replicate_systems b
        JOIN experiment_replicates r ON r.id = b.replicate_id AND NOT r.is_deleted
        JOIN experiment_groups g ON g.id = r.group_id AND NOT g.is_deleted
        JOIN experiments e ON e.id = g.experiment_id AND NOT e.is_deleted AND e.audience = 'sealed'
    WHERE NOT b.is_deleted;
"""

BOOKING_DROP = """
DROP VIEW IF EXISTS experiment_cells;
DROP TRIGGER IF EXISTS trg_systems_parent_booked ON systems;
DROP FUNCTION IF EXISTS system_parent_booked();
DROP TRIGGER IF EXISTS trg_tanks_system_booked ON tanks;
DROP FUNCTION IF EXISTS tank_system_booked();
DROP FUNCTION IF EXISTS system_booked_from_today(uuid);
DROP TRIGGER IF EXISTS trg_experiment_replicate_systems_frozen ON experiment_replicate_systems;
DROP TRIGGER IF EXISTS trg_experiment_replicate_systems_holds ON experiment_replicate_systems;
DROP FUNCTION IF EXISTS experiment_booking_holds();
DROP TRIGGER IF EXISTS trg_experiment_replicate_units_booking ON experiment_replicate_units;
DROP FUNCTION IF EXISTS experiment_booking_tag();
"""


# The frozen rule as 0002 wrote it, to go back to.
_FROZEN_0002 = import_module('experiments.migrations.0002_design_frozen').FROZEN
FROZEN_V1 = _FROZEN_0002[_FROZEN_0002.index('CREATE FUNCTION experiment_frozen()'):
                         _FROZEN_0002.index('$$ LANGUAGE plpgsql;', _FROZEN_0002.index('CREATE FUNCTION experiment_frozen()'))
                         + len('$$ LANGUAGE plpgsql;')].replace('CREATE FUNCTION', 'CREATE OR REPLACE FUNCTION')


class Migration(migrations.Migration):

    dependencies = [
        ('auth', '0012_alter_user_first_name_max_length'),
        ('experiments', '0002_design_frozen'),
        ('farm', '0026_production_form_other'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='SealedCell',
            fields=[
                ('id', models.UUIDField(primary_key=True, serialize=False)),
                ('from_on', models.DateField()),
                ('until_on', models.DateField()),
                ('work', models.UUIDField(db_column='experiment_id')),
            ],
            options={
                'verbose_name': 'sealed cell',
                'verbose_name_plural': 'sealed cells',
                'db_table': 'experiment_cells',
                'managed': False,
            },
        ),
        migrations.CreateModel(
            name='ExperimentShare',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('part', models.CharField(choices=[('design', 'Design'), ('results', 'Results'), ('systems', 'Systems and tanks'), ('data', 'Data'), ('water', 'Water')], max_length=8, verbose_name='Part')),
                ('valid_from', models.DateTimeField(default=django.utils.timezone.now, verbose_name='From')),
                ('valid_until', models.DateTimeField(verbose_name='Until')),
                ('reason', models.CharField(max_length=300, verbose_name='Reason')),
                ('revoked_at', models.DateTimeField(blank=True, null=True, verbose_name='Revoked at')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Created at')),
            ],
            options={
                'verbose_name': 'experiment share',
                'verbose_name_plural': 'experiment shares',
                'db_table': 'experiment_shares',
                'ordering': ['-valid_from', 'id'],
            },
        ),
        migrations.CreateModel(
            name='ReplicateSystem',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Created at')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Updated at')),
                ('version', models.PositiveIntegerField(default=1, verbose_name='Version')),
                ('is_deleted', models.BooleanField(db_index=True, default=False, verbose_name='Deleted')),
                ('deleted_at', models.DateTimeField(blank=True, null=True, verbose_name='Deleted at')),
                ('from_on', models.DateField(verbose_name='From')),
                ('until_on', models.DateField(verbose_name='Until')),
                ('left_reason', models.CharField(blank=True, max_length=500, verbose_name='Reason it left')),
            ],
            options={
                'verbose_name': 'system booking',
                'verbose_name_plural': 'system bookings',
                'db_table': 'experiment_replicate_systems',
                'ordering': ['from_on', 'id'],
            },
        ),
        migrations.AlterModelOptions(
            name='experiment',
            options={'ordering': ['-created_at'], 'permissions': [('oversee_experiment', 'Can oversee the tanks of experiments')], 'verbose_name': 'experiment', 'verbose_name_plural': 'experiments'},
        ),
        migrations.RemoveConstraint(
            model_name='member',
            name='chk_experiment_members_role',
        ),
        migrations.AddField(
            model_name='experiment',
            name='approval_ref',
            field=models.CharField(blank=True, db_default='', default='', max_length=60, verbose_name='Approval reference'),
        ),
        migrations.AddField(
            model_name='experiment',
            name='approval_valid_until',
            field=models.DateField(blank=True, null=True, verbose_name='Approval valid until'),
        ),
        migrations.AddField(
            model_name='experiment',
            name='audience',
            field=models.CharField(choices=[('sealed', 'Team and shares only'), ('open', 'Everyone who reads experiments')], db_default='sealed', default='sealed', max_length=6, verbose_name='Who may read it'),
        ),
        migrations.AddField(
            model_name='experiment',
            name='contact_phone',
            field=models.CharField(blank=True, db_default='', default='', max_length=30, verbose_name='Contact phone'),
        ),
        migrations.AddField(
            model_name='member',
            name='valid_from',
            field=models.DateTimeField(blank=True, null=True, verbose_name='From'),
        ),
        migrations.AddField(
            model_name='member',
            name='valid_until',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Until'),
        ),
        migrations.AlterField(
            model_name='member',
            name='role',
            field=models.CharField(choices=[('lead', 'Lead'), ('researcher', 'Researcher'), ('student', 'Student'), ('technician', 'Technician'), ('advisor', 'Advisor'), ('guest', 'Guest')], default='researcher', max_length=12, verbose_name='Role'),
        ),
        migrations.AddConstraint(
            model_name='experiment',
            constraint=models.CheckConstraint(condition=models.Q(('audience__in', ['sealed', 'open'])), name='chk_experiments_audience'),
        ),
        migrations.AddConstraint(
            model_name='experiment',
            constraint=models.CheckConstraint(condition=models.Q(('approval_valid_until__isnull', True), models.Q(('approval_ref', ''), _negated=True), _connector='OR'), name='chk_experiments_approval', violation_error_message="An approval's validity needs its reference."),
        ),
        migrations.AddConstraint(
            model_name='member',
            constraint=models.CheckConstraint(condition=models.Q(('role__in', ['lead', 'researcher', 'student', 'technician', 'advisor', 'guest'])), name='chk_experiment_members_role'),
        ),
        migrations.AddConstraint(
            model_name='member',
            constraint=models.CheckConstraint(condition=models.Q(('valid_from__isnull', True), ('valid_until__isnull', True), ('valid_until__gt', models.F('valid_from')), _connector='OR'), name='chk_experiment_members_window', violation_error_message='The window ends after it begins.'),
        ),
        migrations.AddField(
            model_name='experimentshare',
            name='created_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Created by'),
        ),
        migrations.AddField(
            model_name='experimentshare',
            name='experiment',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='shares', to='experiments.experiment', verbose_name='Experiment'),
        ),
        migrations.AddField(
            model_name='experimentshare',
            name='group',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='experiment_shares', to='auth.group', verbose_name='Role'),
        ),
        migrations.AddField(
            model_name='experimentshare',
            name='revoked_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Revoked by'),
        ),
        migrations.AddField(
            model_name='experimentshare',
            name='user',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='experiment_shares', to=settings.AUTH_USER_MODEL, verbose_name='Person'),
        ),
        migrations.AddField(
            model_name='replicatesystem',
            name='created_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Created by'),
        ),
        migrations.AddField(
            model_name='replicatesystem',
            name='deleted_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Deleted by'),
        ),
        migrations.AddField(
            model_name='replicatesystem',
            name='replicate',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='system_bookings', to='experiments.replicate', verbose_name='Replicate'),
        ),
        migrations.AddField(
            model_name='replicatesystem',
            name='system',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='experiment_bookings', to='farm.system', verbose_name='System'),
        ),
        migrations.AddField(
            model_name='replicatesystem',
            name='updated_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Updated by'),
        ),
        migrations.AddField(
            model_name='replicateunit',
            name='booking',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='placements', to='experiments.replicatesystem', verbose_name='System booking'),
        ),
        migrations.AddIndex(
            model_name='experimentshare',
            index=models.Index(fields=['user', 'valid_until'], name='idx_experiment_shares_user'),
        ),
        migrations.AddIndex(
            model_name='experimentshare',
            index=models.Index(fields=['group', 'valid_until'], name='idx_experiment_shares_group'),
        ),
        migrations.AddConstraint(
            model_name='experimentshare',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('group__isnull', True), ('user__isnull', False)), models.Q(('group__isnull', False), ('user__isnull', True)), _connector='OR'), name='chk_experiment_shares_grantee', violation_error_message='A share is for one person or one role.'),
        ),
        migrations.AddConstraint(
            model_name='experimentshare',
            constraint=models.CheckConstraint(condition=models.Q(('part__in', ['design', 'results', 'systems', 'data', 'water'])), name='chk_experiment_shares_part'),
        ),
        migrations.AddConstraint(
            model_name='experimentshare',
            constraint=models.CheckConstraint(condition=models.Q(('valid_until__gt', models.F('valid_from'))), name='chk_experiment_shares_period', violation_error_message='A share ends after it begins.'),
        ),
        migrations.AddConstraint(
            model_name='experimentshare',
            constraint=models.CheckConstraint(condition=models.Q(('valid_until__lte', django.db.models.expressions.CombinedExpression(models.F('valid_from'), '+', models.Value(datetime.timedelta(days=730))))), name='chk_experiment_shares_length', violation_error_message='A share lasts at most two years: renew it when it ends.'),
        ),
        migrations.AddConstraint(
            model_name='experimentshare',
            constraint=models.CheckConstraint(condition=models.Q(('reason', ''), _negated=True), name='chk_experiment_shares_reason', violation_error_message='Say why it is shared.'),
        ),
        migrations.AddConstraint(
            model_name='experimentshare',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('revoked_at__isnull', True), ('revoked_by__isnull', True)), models.Q(('revoked_at__isnull', False), ('revoked_by__isnull', False)), _connector='OR'), name='chk_experiment_shares_revoked'),
        ),
        migrations.AddConstraint(
            model_name='experimentshare',
            constraint=models.UniqueConstraint(condition=models.Q(('revoked_at__isnull', True), ('user__isnull', False)), fields=('experiment', 'user', 'part'), name='uq_experiment_shares_user_part', violation_error_message='This person already holds this part.'),
        ),
        migrations.AddConstraint(
            model_name='experimentshare',
            constraint=models.UniqueConstraint(condition=models.Q(('group__isnull', False), ('revoked_at__isnull', True)), fields=('experiment', 'group', 'part'), name='uq_experiment_shares_group_part', violation_error_message='This role already holds this part.'),
        ),
        migrations.AddIndex(
            model_name='replicatesystem',
            index=models.Index(fields=['system', 'from_on'], name='idx_experiment_bookings_system'),
        ),
        migrations.AddConstraint(
            model_name='replicatesystem',
            constraint=models.CheckConstraint(condition=models.Q(('until_on__gte', models.F('from_on'))), name='chk_experiment_bookings_period', violation_error_message='The last day comes on or after the first day.'),
        ),
        migrations.AddConstraint(
            model_name='replicatesystem',
            constraint=django.contrib.postgres.constraints.ExclusionConstraint(condition=models.Q(('is_deleted', False)), expressions=[(models.F('system'), '='), (core.ranges.DateRange(models.F('from_on'), models.F('until_on'), models.Value('[]')), '&&')], name='excl_replicate_systems_system', violation_error_message='This system is booked on some of these days.'),
        ),
        migrations.RunSQL(FROZEN_V2, reverse_sql=FROZEN_V1),
        migrations.RunSQL(BOOKING, reverse_sql=BOOKING_DROP),
    ]
