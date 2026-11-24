"""The data-layering audit, L-1: the review of a knowledge entry is written by knowledge.services.review, which asks who
may itself (core.access.require) and refuses a review of words that changed since they were read."""
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied

from core.crud import Crossed

from .. import services
from ..models import KnowledgeEntry
from .test_entries import EntryTestCase, stored


class ReviewServiceTests(EntryTestCase):
    def test_who_may_not_edit_entries_is_refused_by_the_service(self):
        entry = self.make()
        stranger = get_user_model().objects.create_user('stranger', 'stranger@example.com', 'x')
        with self.assertRaises(PermissionDenied):
            services.review(stranger, entry.pk, 'reviewed', entry.version)
        self.assertEqual(stored(entry, 'status'), ('draft',))

    def test_a_review_of_changed_words_is_refused_and_writes_nothing(self):
        entry = self.make()
        with self.assertRaises(Crossed):
            services.review(self.user, entry.pk, 'reviewed', entry.version + 1)
        self.assertEqual(stored(entry, 'status', 'version'), ('draft', entry.version))
        reviewed = services.review(self.user, entry.pk, 'reviewed', entry.version)
        self.assertEqual((reviewed.status, reviewed.reviewed_by, KnowledgeEntry.objects.get(pk=entry.pk).version),
                         ('reviewed', self.user, entry.version + 1))
