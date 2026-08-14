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

        # The full-book PDF is public by default, which is wrong for a gated
        # book and fails silently. Warn rather than refuse — the default is a
        # deliberate choice, but a site that forgot to override it should hear
        # about it at boot, not from a reader who downloaded the whole book.
        import warnings as _warnings

        from django.db import DatabaseError

        from .printing import public_book_pdf_warnings
        try:
            for message in public_book_pdf_warnings():
                _warnings.warn(message, RuntimeWarning)
        except DatabaseError:
            pass  # no tables yet (migrate/collectstatic on a fresh install)
