from django.test.runner import DiscoverRunner
from django.test.utils import override_settings


class FastPasswordRunner(DiscoverRunner):
    """Password hashing is made deliberately slow; tests create many users and do not need that."""

    def setup_test_environment(self, **kwargs):
        super().setup_test_environment(**kwargs)
        self._fast_hasher = override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
        self._fast_hasher.enable()

    def teardown_test_environment(self, **kwargs):
        self._fast_hasher.disable()
        super().teardown_test_environment(**kwargs)
