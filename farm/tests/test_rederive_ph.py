"""The stored samples whose pH was measured on another scale than NBS, put on the NBS scale again by formula 4
(farm/water/rederive.py, `manage.py rederive_ph`, the check farm.W001; the water-chemistry audit of 2026-11-19, consensus
point 8): the same measurement gives the same NBS pH whether it was typed before or after the formula changed; what was
measured never moves; each rewrite is in the activity log with the old value; a second run changes nothing; a sample the
conversion now refuses is left as it was and named."""
from decimal import Decimal as D
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError

from core.models import AuditLog

from .. import withdrawal_gate
from ..checks import ph_converted_by_an_older_formula
from ..models import Tank, WaterMeasurement
from ..water import native, rederive
from .test_ph_scale import SeaTestCase


def formula_3(ph, scale, temp_c, salinity):
    """The NBS pH formula 3 put a pH on `scale` at, at the pH column's two decimals."""
    return D(str(round(native.water_equilibria(temp_c, salinity, formula=3).ph_nbs(ph, scale), 2)))


def formula_4(ph, scale, temp_c, salinity):
    return D(str(round(native.water_equilibria(temp_c, salinity, formula=4).ph_nbs(ph, scale), 2)))


class RederiveTests(SeaTestCase):
    def as_formula_3(self, sample):
        """The sample as formula 3 wrote it: its NBS pH by formula 3's step, the formula 3 (what the database held before
        formula 4)."""
        old = formula_3(float(sample.ph_as_measured), sample.ph_scale, float(sample.temperature_c),
                        float(sample.salinity_ppt))
        with withdrawal_gate.opened('test fixture: a sample as formula 3 wrote it'):
            WaterMeasurement.all_objects.filter(pk=sample.pk).update(ph=old, ph_converted_formula=3)
        return old

    def run_command(self, *args):
        out, err = StringIO(), StringIO()
        call_command('rederive_ph', *args, stdout=out, stderr=err)
        return out.getvalue(), err.getvalue()

    def test_a_formula_3_sample_gets_formula_4s_nbs_ph_logged_with_the_old_value(self):
        sample = self.record(ph='7.95', temperature_c='2', salinity_ppt='34', tan_mg_l='1')
        typed_today = WaterMeasurement.objects.get(pk=sample.pk).ph
        self.assertEqual((typed_today, sample.ph_converted_formula), (formula_4(7.95, 'total', 2.0, 34.0), 4))
        old = self.as_formula_3(sample)
        self.assertNotEqual(old, typed_today)                       # the step moved: 2 °C, S 34
        self.assertEqual([warning.id for warning in ph_converted_by_an_older_formula(None)], ['farm.W001'])
        logged = AuditLog.objects.count()
        out, err = self.run_command()
        stored = WaterMeasurement.all_objects.get(pk=sample.pk)
        # The same measurement, the same number as typed today; what was measured, its scale, temperature and salinity
        # untouched; the version moves on.
        self.assertEqual((stored.ph, stored.ph_converted_formula), (typed_today, 4))
        self.assertEqual((stored.ph_as_measured, stored.ph_scale, stored.temperature_c, stored.salinity_ppt),
                         (D('7.95'), 'total', D('2.0'), D('34.0')))
        self.assertEqual(stored.version, sample.version + 1)
        self.assertIn('1 sample(s) on an older formula; 1 NBS pH(s) changed, 0 the same, 0 not converted again.', out)
        self.assertIn(f'pH NBS {old} by formula 3 -> {typed_today} by formula 4', out)
        self.assertEqual(err, '')
        entry = AuditLog.objects.order_by('-created_at').first()
        self.assertEqual(AuditLog.objects.count(), logged + 1)
        self.assertEqual((entry.action, entry.entity_id, entry.user_name), ('update', str(sample.pk), 'system'))
        self.assertEqual(entry.changes['PH (NBS scale)'], [str(old), str(typed_today)])
        self.assertEqual(entry.changes['Formula the pH was put on the NBS scale by'], ['3', '4'])
        self.assertEqual(entry.changes['Why'], [None, {'msgid': rederive.WHY}])
        self.assertEqual(ph_converted_by_an_older_formula(None), [])

    def test_a_second_run_changes_nothing(self):
        sample = self.record(ph='7.95', temperature_c='12', salinity_ppt='20')
        self.as_formula_3(sample)
        self.run_command()
        before = (list(WaterMeasurement.all_objects.values_list('pk', 'ph', 'ph_converted_formula', 'version')),
                  AuditLog.objects.count())
        out, _err = self.run_command()
        self.assertIn('0 sample(s) on an older formula', out)
        self.assertEqual((list(WaterMeasurement.all_objects.values_list('pk', 'ph', 'ph_converted_formula', 'version')),
                          AuditLog.objects.count()), before)

    def test_the_dry_run_writes_nothing(self):
        sample = self.record(ph='7.95', temperature_c='2', salinity_ppt='34')
        old = self.as_formula_3(sample)
        logged = AuditLog.objects.count()
        out, _err = self.run_command('--dry-run')
        self.assertIn('Dry run: nothing is written.', out)
        self.assertIn('1 NBS pH(s) would change', out)
        self.assertEqual(WaterMeasurement.all_objects.get(pk=sample.pk).ph, old)
        self.assertEqual(AuditLog.objects.count(), logged)

    def test_the_same_nbs_ph_is_rewritten_with_its_formula_only(self):
        # Warm water at S 35: the two steps round to the same two decimals (8.0856 and 8.0906).
        sample = self.record(ph='7.95', temperature_c='25', salinity_ppt='35')
        old = self.as_formula_3(sample)
        self.assertEqual((old, formula_4(7.95, 'total', 25.0, 35.0)), (D('8.09'), D('8.09')))
        out, _err = self.run_command()
        self.assertIn('0 NBS pH(s) changed, 1 the same', out)
        stored = WaterMeasurement.all_objects.get(pk=sample.pk)
        self.assertEqual((stored.ph, stored.ph_converted_formula), (old, 4))
        entry = AuditLog.objects.order_by('-created_at').first()
        self.assertNotIn('PH (NBS scale)', entry.changes)
        self.assertEqual(entry.changes['Formula the pH was put on the NBS scale by'], ['3', '4'])

    def test_voided_samples_too_and_a_named_user(self):
        sample = self.record(ph='7.95', temperature_c='2', salinity_ppt='34')
        self.as_formula_3(sample)
        with withdrawal_gate.opened('test fixture: a voided sample'):
            WaterMeasurement.all_objects.filter(pk=sample.pk).update(is_deleted=True, void_reason='typed twice')
        out, _err = self.run_command('--user', self.user.username)
        self.assertIn('(voided or deleted)', out)
        self.assertEqual(WaterMeasurement.all_objects.get(pk=sample.pk).ph_converted_formula, 4)
        self.assertEqual(AuditLog.objects.order_by('-created_at').first().user_name, self.user.username)
        with self.assertRaisesMessage(CommandError, "No user 'nobody'."):
            self.run_command('--user', 'nobody')

    def test_a_sample_the_conversion_now_refuses_is_left_as_it_was_and_named(self):
        sample = self.record(ph='7.95', temperature_c='2', salinity_ppt='34')
        old = self.as_formula_3(sample)
        # Its unit says since then that its water is fresh water with salt added: no seawater scale is taken.
        Tank.objects.filter(pk=self.sea.pk).update(water_type='brackish', water_origin='salt_added')
        logged = AuditLog.objects.count()
        out, err = self.run_command()
        self.assertIn('1 not converted again', out)
        self.assertIn('NOT converted again (not_sea)', out)
        self.assertIn('left as they were', err)
        stored = WaterMeasurement.all_objects.get(pk=sample.pk)
        self.assertEqual((stored.ph, stored.ph_converted_formula), (old, 3))
        self.assertEqual(AuditLog.objects.count(), logged)
        self.assertEqual([warning.id for warning in ph_converted_by_an_older_formula(None)], ['farm.W001'])

    def test_nbs_samples_are_never_read(self):
        self.record(ph_scale='nbs', ph='7.95', temperature_c='2', salinity_ppt='34')
        self.assertEqual(list(rederive.stale()), [])
        self.assertEqual(ph_converted_by_an_older_formula(None), [])
