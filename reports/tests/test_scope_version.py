"""The rows a report reads for its fingerprint changed for the weekly lice report (F-206: earlier counts, the harvest
plans; F-239: lice medicines given for another reason) and the planned slaughter (F-085: the harvests its plans were
recorded as). A report filed before keeps being compared by the rule it was filed under, so the deploy does not flag
every recent filing as "records changed since filing" (cross-review 2, 12)."""
from datetime import datetime, timezone as utc

from django.test import override_settings

from .. import compute, due, services
from ..models import Report, ReportSnapshot
from .helpers import previewed
from .test_due import TODAY
from .test_lice import WARM, WEEK_44, LiceTestCase, temperature


@override_settings(STOCK_BACKDATE_DAYS=3650)
class ScopeVersionTests(LiceTestCase):
    def setUp(self):
        super().setUp()
        self.count(self.m1, 10, 20)                         # an earlier count: read by version 2 only
        self.count(self.m1, 10, 27)
        self.count(self.m2, 10, 28)

    def file(self):
        with temperature(WARM):
            shown = previewed(self.draft)
            services.submit(self.user, self.draft, submitted_at=datetime(2026, 11, 2, 9, tzinfo=utc.utc),
                            channel='altinn', reference='LUS-1', version=self.draft.version, content_sha256=shown)
        return ReportSnapshot.objects.get(report=self.draft)

    def test_a_filing_keeps_the_scope_version_it_was_fingerprinted_with(self):
        snapshot = self.file()
        self.assertEqual(snapshot.scope_version, compute.SCOPE_VERSIONS['sea_lice'])
        self.assertEqual(compute.SCOPE_VERSIONS, {'sea_lice': 2, 'slaughter_planned': 2})

    def test_a_report_filed_under_the_old_scope_is_compared_with_it(self):
        self.draft.delete()                                 # the week's report is the one filed before
        report = Report.objects.create(kind=Report.Kind.SEA_LICE, site=self.sea, period_start=WEEK_44.start,
                                       submitted_at=datetime(2026, 11, 2, 9, tzinfo=utc.utc), channel='altinn',
                                       reference='LUS-0')
        old = compute.fingerprint(compute.scope(report, version=1))
        # As the deploy finds a report filed before: fingerprinted over version 1's rows, with no version said.
        ReportSnapshot.objects.create(report=report, format_version=compute.FORMAT_VERSION, content={'kind': 'sea_lice'},
                                      content_sha256=compute.content_hash({'kind': 'sea_lice'}), sources_fingerprint=old)
        self.assertNotEqual(old, compute.fingerprint(compute.scope(report)))      # version 2 reads more rows
        self.assertEqual(due.no_longer_match(TODAY), [])
