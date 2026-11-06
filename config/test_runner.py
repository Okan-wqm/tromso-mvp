from django.test.runner import DiscoverRunner
from django.test.utils import override_settings

from core import sealing


class FastPasswordRunner(DiscoverRunner):
    """Password hashing is made deliberately slow; tests create many users and do not need that. A test reads as the
    system (core.sealing), and its requests as their person: a test that reads as someone says so (`sealing.as_viewer`)."""

    def setup_test_environment(self, **kwargs):
        super().setup_test_environment(**kwargs)
        sealing.enter_process_system('tests')
        self._fast_hasher = override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
        self._fast_hasher.enable()

    def teardown_test_environment(self, **kwargs):
        self._fast_hasher.disable()
        super().teardown_test_environment(**kwargs)
