from django.apps import AppConfig


class TasksConfig(AppConfig):
    name = 'tasks'

    def ready(self):
        from . import resources  # noqa: F401  declares the tabs on Resource.registry
        from .sealing import declare_all
        declare_all()       # how this app's records are sealed (core.sealing)
