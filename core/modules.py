"""What a file of the project is, read from its path. `is_test_module` is the one predicate that tells test code from
production for every reader of the code: rule S and the layering guards (core/tests_data_access.py), the data map's
tests that mention a model (core.datamap), the sealing and simple-database guards, the formula doors' callers, the
clock, date-input, escaping and lean-endpoint guards, and HR's own code-reading tests. Production may import this
module (core.datamap does); core.testing hands the predicate on to the tests."""
from pathlib import PurePath


def is_test_module(path):
    """Whether a file of the project is test code: a module in a `tests` folder, or named `tests.py`, `test_*.py`,
    `tests_*.py` or `testing.py` (core.testing: the tests' support, which production code never imports). `path` is
    relative to the project (settings.BASE_DIR); an absolute one is refused (ValueError), so where a checkout is
    mounted (a folder named tests above it) never decides."""
    path = PurePath(path)
    if path.is_absolute():
        raise ValueError(f'{path}: give the path relative to the project')
    parts = path.parts
    return 'tests' in parts[:-1] or parts[-1] in ('tests.py', 'testing.py') or parts[-1].startswith(('test_', 'tests_'))
