"""The data-layering audit, L-7: the withdrawal what-if of a restore (farm.health.withdrawal.blockers_while_live) weighs
the record as it would stand live and leaves the caller's object as it was: it never hands back an object that says
live while its row is deleted."""
from django.test import TestCase

from farm.health import withdrawal
from farm.models import Species

from .helpers import make_species


class WhatIfLeavesTheObjectTests(TestCase):
    def test_a_restore_weighed_leaves_the_object_deleted(self):
        species = make_species()
        Species.all_objects.filter(pk=species.pk).update(is_deleted=True)
        stored = Species.all_objects.get(pk=species.pk)
        self.assertEqual(withdrawal.blockers_while_live(stored), [])
        self.assertTrue(stored.is_deleted)
        self.assertTrue(Species.all_objects.get(pk=species.pk).is_deleted)       # the row too: rolled back
