"""What the regulatory reports need of the farm (docs/regulatory-reports.md, 5.3 and section 6): the site's
organisation number (OUR-12; the override's free text becomes nine digits, a value that is not nine digits goes to
the site's notes), production form (D-13) and reports-from date (D-6); unit numbers unique per production
department (OUR-07; per site in the model's clean); a batch's provenance (backfilled from its origin where the
origin says it) and year class (D-14, never defaulted); the official causes of a cleaner fish's cull (OUR-08); a
feeding's target (D-1); a feed's dry or wet form (OUR-17)."""
import re

import django.core.validators

from django.db import migrations, models

NINE_DIGITS = re.compile(r'[0-9]{9}')


def organisation_numbers(apps, schema_editor):
    Site = apps.get_model('farm', 'Site')
    for site in Site._base_manager.exclude(organisation_number_override=''):
        typed = site.organisation_number_override
        digits = ''.join(typed.split())
        if NINE_DIGITS.fullmatch(digits):
            site.organisation_number_override = digits
        else:
            note = f'Organisation number override before 2026-11-03, not 9 digits: {typed}'
            site.notes = f'{site.notes}\n{note}' if site.notes else note
            site.organisation_number_override = ''
        site.save(update_fields=['organisation_number_override', 'notes'])


def provenances(apps, schema_editor):
    Batch = apps.get_model('farm', 'Batch')
    Batch._base_manager.filter(origin='own_hatchery').update(provenance='farmed')
    Batch._base_manager.filter(origin='wild').update(provenance='wild_caught')


class Migration(migrations.Migration):

    dependencies = [
        ('farm', '0018_health'),    # 0019_water_points once main has it
    ]

    operations = [
        # ---- the site -----------------------------------------------------------------------------------
        migrations.RunPython(organisation_numbers, migrations.RunPython.noop),
        migrations.RenameField(model_name='site', old_name='organisation_number_override',
                               new_name='organisation_number'),
        migrations.AlterField(
            model_name='site',
            name='organisation_number',
            field=models.CharField(blank=True, max_length=9, verbose_name='Organisation number'),
        ),
        migrations.AddField(
            model_name='site',
            name='production_form',
            field=models.CharField(blank=True, choices=[('settefisk', 'Juveniles (settefisk)'), ('matfisk', 'Food fish (matfisk)'), ('stamfisk', 'Broodstock (stamfisk)')], max_length=10, verbose_name='Production form'),
        ),
        migrations.AddField(
            model_name='site',
            name='reports_from',
            field=models.DateField(blank=True, null=True, verbose_name='Reports from'),
        ),
        migrations.AddConstraint(
            model_name='site',
            constraint=models.CheckConstraint(condition=models.Q(('organisation_number', ''), ('organisation_number__regex', '^[0-9]{9}$'), _connector='OR'), name='chk_sites_organisation_number', violation_error_message='An organisation number is 9 digits.'),
        ),
        migrations.AddConstraint(
            model_name='site',
            constraint=models.CheckConstraint(condition=models.Q(('production_form', ''), ('production_form__in', ['settefisk', 'matfisk', 'stamfisk']), _connector='OR'), name='chk_sites_production_form'),
        ),
        # ---- the unit's number: per production department in the database, per site in clean() --------------
        migrations.RemoveConstraint(
            model_name='tank',
            name='uq_tanks_regulatory_unit_id_live',
        ),
        migrations.AddConstraint(
            model_name='tank',
            constraint=models.UniqueConstraint(condition=models.Q(('is_deleted', False), models.Q(('regulatory_unit_id', ''), _negated=True)), fields=('production_department', 'regulatory_unit_id'), name='uq_tanks_regulatory_unit_id_live', violation_error_message='Another unit of the site already has this regulatory unit ID.'),
        ),
        # ---- the batch ------------------------------------------------------------------------------------
        migrations.AddField(
            model_name='batch',
            name='provenance',
            field=models.CharField(blank=True, choices=[('farmed', 'Farmed'), ('wild_caught', 'Wild-caught')], max_length=12, verbose_name='Farmed or wild-caught'),
        ),
        migrations.AddField(
            model_name='batch',
            name='year_class',
            field=models.PositiveSmallIntegerField(blank=True, null=True, validators=[django.core.validators.MinValueValidator(1980, 'A year class is a year, e.g. 2026.'), django.core.validators.MaxValueValidator(2100, 'A year class is a year, e.g. 2026.')], verbose_name='Year class'),
        ),
        migrations.RunPython(provenances, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='batch',
            constraint=models.CheckConstraint(condition=models.Q(('provenance', ''), ('provenance__in', ['farmed', 'wild_caught']), _connector='OR'), name='chk_batches_provenance'),
        ),
        migrations.AddConstraint(
            model_name='batch',
            constraint=models.CheckConstraint(condition=models.Q(('origin', 'purchased'), models.Q(('origin', 'own_hatchery'), ('provenance', 'farmed')), models.Q(('origin', 'wild'), ('provenance', 'wild_caught')), _connector='OR'), name='chk_batches_origin_provenance', violation_error_message='Fish of the own hatchery are farmed, fish caught in the wild wild-caught.'),
        ),
        migrations.AddConstraint(
            model_name='batch',
            constraint=models.CheckConstraint(condition=models.Q(('year_class__isnull', True), models.Q(('year_class__gte', 1980), ('year_class__lte', 2100)), _connector='OR'), name='chk_batches_year_class', violation_error_message='A year class is a year, e.g. 2026.'),
        ),
        # ---- a cull's reasons: the official causes of a cleaner fish's cull join the list ----------------------
        migrations.RemoveConstraint(
            model_name='stockmovement',
            name='chk_stock_movements_reason',
        ),
        migrations.AddConstraint(
            model_name='stockmovement',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(models.Q(('kind__in', ['mortality', 'cull', 'transfer_out', 'adjustment']), _negated=True), ('reason', '')), models.Q(('kind', 'mortality'), ('reason__in', ['disease', 'water_quality', 'oxygen', 'temperature', 'ammonia', 'stress', 'handling', 'predation', 'cannibalism', 'starvation', 'genetic', 'treatment', 'unknown', 'other'])), models.Q(('kind', 'cull'), ('reason__in', ['small_size', 'deformed', 'sick', 'poor_growth', 'grading', 'quality', 'other', 'injured', 'emaciated', 'salmon_handling', 'poor_environment', 'not_used'])), models.Q(('kind', 'transfer_out'), ('reason__in', ['density', 'split', 'grading', 'growth_stage', 'water_quality', 'health', 'maintenance', 'harvest_prep', 'other'])), models.Q(('kind', 'adjustment'), ('reason__in', ['count_correction', 'unaccounted_loss', 'escape', 'other'])), _connector='OR'), name='chk_stock_movements_reason'),
        ),
        # ---- feeding and feed -------------------------------------------------------------------------------
        migrations.AddField(
            model_name='feedingrecord',
            name='target',
            field=models.CharField(choices=[('production', 'Production fish'), ('cleaner_fish', 'Cleaner fish')], default='production', max_length=12, verbose_name='Fed to'),
        ),
        migrations.AddConstraint(
            model_name='feedingrecord',
            constraint=models.CheckConstraint(condition=models.Q(('target__in', ['production', 'cleaner_fish'])), name='chk_feeding_records_target'),
        ),
        migrations.AddField(
            model_name='feed',
            name='feed_form',
            field=models.CharField(choices=[('dry', 'Dry'), ('wet', 'Wet')], default='dry', max_length=3, verbose_name='Dry or wet'),
        ),
        migrations.AddConstraint(
            model_name='feed',
            constraint=models.CheckConstraint(condition=models.Q(('feed_form__in', ['dry', 'wet'])), name='chk_feeds_feed_form'),
        ),
    ]
