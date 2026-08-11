from django.apps import AppConfig


class ParodyWebConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "parody_web"
    verbose_name = "Parody Web"

    def ready(self):
        # Fail on a malformed PARODY_WEB_THEME or PARODY_WEB_ACCESS_POLICY at
        # startup rather than silently dropping it at first render.
        from django.conf import settings

        from .access import validate_policy
        from .theme import validate_theme
        validate_theme(getattr(settings, "PARODY_WEB_THEME", None))
        validate_policy(getattr(settings, "PARODY_WEB_ACCESS_POLICY", ""))
