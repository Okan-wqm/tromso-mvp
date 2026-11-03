from django.apps import AppConfig


class KnowledgeConfig(AppConfig):
    """The company's knowledge: the library of documents and the knowledge entries taken from them, which AI
    agents will later watch the farm with (README, Knowledge)."""

    name = 'knowledge'

    def ready(self):
        from . import resources  # noqa: F401  declares the tabs on Resource.registry
