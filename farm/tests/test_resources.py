from django.test import SimpleTestCase

from core import audit

from ..resources import DepartmentResource, SiteResource


class ResourceTests(SimpleTestCase):
    def test_a_tab_and_the_delete_plan_name_records_the_same_way_in_the_activity_log(self):
        # The delete plan logs the records it touches by their model's name; a tab searches the history
        # by its own. If the two drifted apart, a record's History tab would miss those entries.
        for resource in (SiteResource, DepartmentResource):
            self.assertEqual(resource.entity_type(), audit.entity_type_of(resource.model))
