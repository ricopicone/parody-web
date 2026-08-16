from django.apps import AppConfig


class ParodyWebAnnotateConfig(AppConfig):
    name = "parody_web_annotate"
    verbose_name = "parody-web annotation"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from . import checks  # noqa: F401  (registers the boot-time check)
