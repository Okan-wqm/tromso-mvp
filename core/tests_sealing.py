"""The seal's registry (core.sealing): every model whose rows lie on a unit or a system, or hang on a batch, a sampling
point, a sensor channel or binding, a stock operation, a health event, a task, a report or an experiment, says how it is
sealed (filtered by the cells, following its parent, or exempt with a written reason). A model added later with such a
link and no declaration fails here and in the system check, so no new table can read past the seal."""
from django.apps import apps
from django.db import models
from django.test import SimpleTestCase
from django.test.utils import isolate_apps

from core import sealing
from farm.models import Tank

# The records a sealed cell reaches: a model with a link to one of these (directly or through other models) is keyed.
KEYED = ('farm.Tank', 'farm.System', 'farm.Batch', 'farm.SamplingPoint', 'farm.Equipment', 'farm.StockOperation',
         'farm.HealthEvent', 'sensors.Binding', 'sensors.Channel', 'tasks.Task', 'reports.Report',
         'experiments.Experiment')


class RegistryTests(SimpleTestCase):
    def test_every_keyed_model_declares_its_seal(self):
        self.assertEqual(sealing.undeclared(apps.get_models()), [])

    def test_the_keyed_records_are_the_ones_named(self):
        self.assertEqual(sorted(sealing.KEYED), sorted(KEYED))

    def test_every_filtered_model_is_filtered_by_each_of_its_managers(self):
        """A filtered model's managers (`objects` and `all_objects`) both carry the seal; only Django's base manager,
        which a link to one record follows, does not."""
        unsealed = [f'{seal.model._meta.label}.{manager.name}' for seal in sealing.registry() if seal.filters
                    for manager in seal.model._meta.managers if not isinstance(manager, sealing.SealedMixin)]
        self.assertEqual(unsealed, [])

    def test_an_exempt_model_says_why(self):
        self.assertEqual([seal.model._meta.label for seal in sealing.registry()
                          if seal.mode == sealing.EXEMPT and len(seal.reason) < 20], [])

    @isolate_apps('core')
    def test_a_new_model_on_a_unit_without_a_declaration_fails_the_check(self):
        class Weighing(models.Model):
            unit = models.ForeignKey(Tank, on_delete=models.PROTECT)

        class WeighingNote(models.Model):
            weighing = models.ForeignKey(Weighing, on_delete=models.CASCADE)

        class Plain(models.Model):
            name = models.CharField(max_length=10)

        self.assertEqual(sealing.undeclared([Weighing, WeighingNote, Plain]),
                         ['core.Weighing', 'core.WeighingNote'])
        errors = sealing.check_registry(models=[Weighing])
        self.assertEqual([error.id for error in errors], ['core.E101'])
