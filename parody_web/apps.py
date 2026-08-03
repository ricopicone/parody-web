from django.apps import AppConfig


class ParodyWebConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "parody_web"
    verbose_name = "Parody Web"

    def ready(self):
        # Fail on a malformed PARODY_WEB_THEME at startup rather than silently
        # dropping it at first render.
        from django.conf import settings

        from .theme import validate_theme
        validate_theme(getattr(settings, "PARODY_WEB_THEME", None))
