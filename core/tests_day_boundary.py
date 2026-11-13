"""The tests that count days, run again with the clock held inside the hours when the server's day (UTC) is not the
company's (core.testing.BAD_HOURS): a test that says "today" on one clock while the code reads another passes all day
and fails there, as five did in CI between 23:00 and 24:00 UTC (run 42921917659, 10.11.2026). Each class below is one
of those five, or a neighbour found by the same sweep (README, Tests). The originals still run on the real clock."""
from core.testing import at_bad_hours
from farm.tests import test_feeding, test_health, test_size_mix
from hr.tests import test_attendance
from monitoring.tests import test_pages

at_bad_hours(globals(),
             test_pages.WallTests,
             test_size_mix.CleanerFishAreAnotherSpeciesTests,
             test_health.WithdrawalTests,
             test_feeding.FiguresTests,
             test_attendance.TodayPageTests)
