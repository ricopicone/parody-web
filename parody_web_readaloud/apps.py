from django.apps import AppConfig


class ParodyWebReadaloudConfig(AppConfig):
    name = "parody_web_readaloud"
    verbose_name = "parody-web read-along"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from . import checks  # noqa: F401  (registers the boot-time check)
