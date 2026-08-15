"""Django system checks for parody-web.

Configuration that can only be judged against the *data* belongs here rather
than in ``AppConfig.ready()``: a query in ``ready()`` runs before the app
registry is populated and trips Django's "Accessing the database during app
initialization is discouraged" warning on every management command. Checks run
after apps are loaded, and `manage.py check` is already part of a deploy.
"""

from django.core.checks import Warning as CheckWarning
from django.core.checks import register


@register()
def public_book_pdf_check(app_configs, **kwargs):
    """Flag a gated book whose whole-book PDF is nonetheless public.

    ``PARODY_WEB_PUBLIC_BOOK_PDF`` defaults to True, which is right for a
    wholly public book and wrong for a gated one — and the failure is silent,
    because serving the PDF looks exactly like success.
    """
    from django.db import DatabaseError, OperationalError, ProgrammingError

    from .printing import public_book_pdf_warnings

    try:
        messages = public_book_pdf_warnings()
    except (DatabaseError, OperationalError, ProgrammingError):
        # No database yet (a fresh install running migrate/collectstatic), or
        # no tables. Nothing to judge; never block the command.
        return []
    return [
        CheckWarning(message, id="parody_web.W001", hint=(
            "Set PARODY_WEB_PUBLIC_BOOK_PDF = False, or confirm the whole "
            "book is meant to be downloadable."))
        for message in messages
    ]
