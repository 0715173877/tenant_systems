from django.apps import AppConfig


class TenantsConfig(AppConfig):
    name = 'tenants'

    def ready(self):
        # Register signal handlers (tenant portal account provisioning).
        from . import signals  # noqa: F401

