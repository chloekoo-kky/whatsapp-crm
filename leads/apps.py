from django.apps import AppConfig


class LeadsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "leads"
    verbose_name = "Leads"

    def ready(self):
        from leads import signals  # noqa: F401

