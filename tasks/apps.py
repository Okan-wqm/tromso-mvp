from django.apps import AppConfig


class TasksConfig(AppConfig):
    name = 'tasks'

    def ready(self):
        from . import resources  # noqa: F401  declares the tabs on Resource.registry
