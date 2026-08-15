from django.apps import AppConfig


class ParodyWebConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "parody_web"
    verbose_name = "Parody Web"

    def ready(self):
        # Fail on a malformed PARODY_WEB_THEME, PARODY_WEB_ACCESS_POLICY or
        # PARODY_WEB_BOOK_RESOLVER at startup rather than silently dropping it
        # at first render.
        from django.conf import settings

        from .access import validate_policy
        from .books import validate_resolver
        from .printing import validate_print_settings
        from .theme import validate_theme
        validate_theme(getattr(settings, "PARODY_WEB_THEME", None))
        validate_policy(getattr(settings, "PARODY_WEB_ACCESS_POLICY", ""))
        validate_resolver(getattr(settings, "PARODY_WEB_BOOK_RESOLVER", ""))
        validate_print_settings(
            getattr(settings, "PARODY_WEB_PRINT_ROOT", ""),
            getattr(settings, "PARODY_WEB_PRINT_CACHE", ""),
            getattr(settings, "PARODY_WEB_PRINT_XACCEL", ""))

        # Registers the gated-book/public-PDF check (see checks.py). It reads
        # the database, so it is a system check rather than something ready()
        # runs directly — querying here trips Django's "Accessing the database
        # during app initialization is discouraged" warning on every
        # manage.py invocation.
        from . import checks  # noqa: F401
