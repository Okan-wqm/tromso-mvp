"""The harvest plan's form says what the planned-slaughter notice needs (flow fault M-12): the form called the planned
kilos "Optional", and the notice then refused to be filed for a plan without them (reports.compute.slaughter: "has no
planned kilos"). The kilos stay optional on the plan (a plan may be made before they are known); the form now says the
notice needs them, and what else it needs of the facility. A planned transport, which no notice reads, keeps "Optional"."""
from django.core.management import call_command
from django.urls import reverse
from django.utils import translation

from ..models import HandlingPlanItem
from .test_harvest import HarvestTestCase

def setUpModule():
    call_command('compile_catalogs', verbosity=0)    # the language test reads the built catalogs


NEEDS = 'the planned-slaughter notice of its week (Production › Reports) reports these kilos and cannot be filed'


class PlanFormTests(HarvestTestCase):
    def form(self, kind):
        return self.client.get(reverse('farm:handlingplanitem_create'), {'kind': kind, 'unit': self.t1.pk})

    def test_a_planned_harvest_says_the_notice_needs_the_kilos_and_the_operators_number(self):
        page = self.form('harvest')
        fields = page.context['form'].fields
        self.assertIn(NEEDS, str(fields['planned_kg'].help_text))
        self.assertNotIn('Optional', str(fields['planned_kg'].help_text))
        self.assertIn('9-digit organisation number', str(fields['facility'].help_text))
        self.assertContains(page, NEEDS)

    def test_a_planned_transport_keeps_optional(self):
        fields = self.form('transport').context['form'].fields
        self.assertEqual(str(fields['planned_kg'].help_text), 'Optional: their round (live) weight, in kg.')

    def test_the_plan_is_still_saved_without_the_kilos(self):
        response = self.client.post(reverse('farm:handlingplanitem_create'), {
            'kind': 'harvest', 'date': self.day(-5).isoformat(), 'unit': str(self.t1.pk), 'batch': str(self.batch.pk),
            'planned_count': '', 'planned_kg': '', 'facility': str(self.facility.pk), 'transport': '', 'vessel': '',
            'notes': '', 'cancelled_reason': ''})
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(HandlingPlanItem.objects.get().planned_kg)

    def test_the_help_is_translated(self):
        self.addCleanup(translation.activate, 'en')
        for language in ('nb', 'tr'):
            with translation.override(language):
                fields = self.form('harvest').context['form'].fields
                for name in ('planned_kg', 'facility'):
                    text = str(fields[name].help_text)
                    self.assertTrue(text and 'planned-slaughter notice' not in text, (language, name))
